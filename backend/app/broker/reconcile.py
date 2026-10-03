"""Background order reconciliation for a broker that fills asynchronously (Webull paper).

Every RECONCILE_INTERVAL_S (15 s) during the regular session (09:30-16:00 ET, NYSE calendar from app.closed.session)
the reconciler calls ``broker.reconcile()``: one read of Webull's open orders, then the final state (order detail) of
each order this app placed that is no longer open, a few per pass (Webull allows 2 detail reads / 2 s). Our order
states (and so GET /orders, staged orders and bridges reading the broker) follow Webull's without waiting for a
request. When the session closes it runs one last pass (orders placed near 16:00 may fill at the close), then idles:
it sleeps until the next regular open, re-checking at most every RECONCILE_IDLE_S so a clock change or a restarted
session is noticed. A broker without ``reconcile`` (the simulator, which fills synchronously) makes it idle too.

Start / stop: ``ensure_started(app)`` (called by the broker routes on first use when the active broker is Webull and
WEBULL_RECONCILE is not 0), POST /broker/reconcile/start, POST /broker/reconcile/stop, GET /broker/reconcile (status).
The router's shutdown hook stops every running reconciler, so nothing outlives the app."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
from collections import deque
from typing import Any, Callable

from .models import BrokerError, now_iso

log = logging.getLogger(__name__)

RECONCILE_INTERVAL_S = 15.0
RECONCILE_IDLE_S = 300.0  # longest idle sleep while the market is closed
BACKOFF_MAX_S = 120.0  # consecutive failures back off 15 s, 30 s, 60 s, 120 s
_RUNNING: set["Reconciler"] = set()


def _session(now: dt.datetime):
    from ..closed.session import session_at

    return session_at(now)


def _now_utc() -> dt.datetime:
    from ..closed.session import now_utc

    return now_utc()


class Reconciler:
    def __init__(self, broker_getter: Callable[[], Any], clock: Callable[[], dt.datetime] | None = None,
                 interval_s: float = RECONCILE_INTERVAL_S, idle_s: float = RECONCILE_IDLE_S,
                 sleep: Callable[[float], Any] = asyncio.sleep) -> None:
        self._broker = broker_getter
        self._clock = clock or _now_utc
        self.interval_s, self.idle_s = interval_s, idle_s
        self._sleep = sleep
        self._task: asyncio.Task | None = None
        self.passes = 0
        self.errors = 0
        self.consecutive_errors = 0
        self.last_run_at: str | None = None
        self.last_result: dict | None = None
        self.last_error: str | None = None
        self.state = "stopped"  # stopped | active | idle
        self.idle_reason: str | None = None
        self.next_run_in_s: float | None = None
        self._was_open = False
        self.recent: deque[dict] = deque(maxlen=50)  # transitions seen, newest last

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> bool:
        """Start the loop on the running event loop; False when it was already running."""
        if self.running:
            return False
        self._task = asyncio.get_running_loop().create_task(self._loop(), name="webull-reconcile")
        _RUNNING.add(self)
        self.state = "active"
        return True

    async def stop(self) -> bool:
        """Stop the loop and wait for it to end; False when it was not running."""
        _RUNNING.discard(self)
        task, self._task = self._task, None
        self.state, self.next_run_in_s = "stopped", None
        if task is None or task.done():
            return False
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        return True

    async def run_once(self, force: bool = False) -> dict:
        """One pass now. Outside the regular session it does nothing (idle) unless ``force`` or it is the pass that
        follows the close."""
        broker = self._broker()
        rec = getattr(broker, "reconcile", None)
        if rec is None:
            self.state, self.idle_reason = "idle", f"broker {getattr(broker, 'name', '?')} fills synchronously"
            return {"ran": False, "reason": self.idle_reason}
        s = _session(self._clock())
        closing_pass = self._was_open and not s.equities_open
        self._was_open = s.equities_open
        if not (s.equities_open or force or closing_pass):
            self.state, self.idle_reason = "idle", f"market closed ({s.label}); next regular open " \
                f"{s.next_open.isoformat().replace('+00:00', 'Z')}"
            return {"ran": False, "reason": self.idle_reason}
        self.state, self.idle_reason = "active", None
        self.last_run_at = now_iso()
        try:
            res = await rec()
        except BrokerError as e:
            self.errors += 1
            self.consecutive_errors += 1
            self.last_error = e.message
            return {"ran": True, "ok": False, "error": e.message}
        except Exception as e:  # never let one bad pass kill the loop
            self.errors += 1
            self.consecutive_errors += 1
            self.last_error = type(e).__name__
            log.warning("reconcile pass failed: %s", type(e).__name__)
            return {"ran": True, "ok": False, "error": type(e).__name__}
        self.passes += 1
        self.consecutive_errors = 0
        self.last_error = None
        self.last_result = {k: v for k, v in res.items() if k != "transitions"}
        self.recent.extend(res.get("transitions") or [])
        return {"ran": True, "ok": True, "closing_pass": closing_pass, **res}

    def _delay(self) -> float:
        s = _session(self._clock())
        if s.equities_open:
            if self.consecutive_errors:
                return min(self.interval_s * 2 ** (self.consecutive_errors - 1), BACKOFF_MAX_S)
            return self.interval_s
        until = (s.next_open - self._clock()).total_seconds()
        return max(1.0, min(until, self.idle_s))

    async def _loop(self) -> None:
        while True:
            await self.run_once()
            delay = self._delay()
            self.next_run_in_s = round(delay, 1)
            await self._sleep(delay)

    def status(self) -> dict:
        b = self._broker()
        s = _session(self._clock())
        return {"running": self.running, "state": self.state if self.running else "stopped",
                "idle_reason": self.idle_reason, "interval_s": self.interval_s, "market_open": s.equities_open,
                "broker": getattr(b, "name", None), "supported": hasattr(b, "reconcile"),
                "passes": self.passes, "errors": self.errors, "last_run_at": self.last_run_at,
                "last_error": self.last_error, "last_result": self.last_result, "next_run_in_s": self.next_run_in_s,
                "recent_transitions": list(self.recent)[-10:], "status_map": status_map()}


def status_map() -> dict:
    from .webull import STATUS_MAP_DOC

    return dict(STATUS_MAP_DOC)


def get_reconciler(app: Any) -> Reconciler:
    """The app's reconciler (one per app), reading the app's active broker on every pass."""
    r = getattr(app.state, "reconciler", None)
    if r is None:
        from . import get_broker

        r = app.state.reconciler = Reconciler(lambda: get_broker(app),
                                              clock=lambda: _app_clock(app))
    return r


def _app_clock(app: Any) -> dt.datetime:
    clock = getattr(app.state, "staged_clock", None)  # tests pin the session clock
    if clock is not None:
        from ..closed.session import to_utc

        return to_utc(clock())
    return _now_utc()


def auto_start_enabled() -> bool:
    """WEBULL_RECONCILE=0 turns auto-start off. Under pytest it is off unless WEBULL_RECONCILE=force, so a test that
    pins a mocked Webull broker never gets background requests it did not ask for."""
    v = os.environ.get("WEBULL_RECONCILE", "1").strip().lower()
    if v == "force":
        return True
    if "PYTEST_CURRENT_TEST" in os.environ:
        return False
    return v not in ("0", "false", "no", "off")


def ensure_started(app: Any) -> bool:
    """Start the app's reconciler when the active broker reconciles (Webull) and WEBULL_RECONCILE is not 0. Called
    from inside a request (a running loop); never raises."""
    try:
        if not auto_start_enabled() or getattr(app.state, "reconcile_stopped_by_user", False):
            return False
        from . import get_broker

        if not hasattr(get_broker(app), "reconcile"):
            return False
        return get_reconciler(app).start()
    except Exception as e:  # pragma: no cover - defensive: a status read must never fail because of this
        log.warning("reconciler auto-start failed: %s", type(e).__name__)
        return False


async def stop_all() -> None:
    for r in list(_RUNNING):
        await r.stop()
