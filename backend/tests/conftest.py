import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parents[2] / "research" / "tests" / "fakes.py"
_spec = importlib.util.spec_from_file_location("research_fakes", _path)
research_fakes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(research_fakes)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_broker(tmp_path, monkeypatch):
    """Every test gets its own sim account file and no live market data (bridges now route orders to a broker)."""
    import app.broker as broker

    monkeypatch.setenv("SIM_ACCOUNT_PATH", str(tmp_path / "sim_account.json"))
    monkeypatch.setenv("BROKER", "sim")
    monkeypatch.setattr(broker, "_quotes", lambda app: broker.NullQuotes())
    broker.reset_default_broker()
    yield
    broker.reset_default_broker()


def pytest_configure(config):
    config.addinivalue_line("markers", "real_twins: read the committed twin map (app/data/kalshi_twins.json) "
                                       "instead of the empty map every other test gets")


@pytest.fixture(autouse=True)
def _empty_twin_map(request, tmp_path, monkeypatch):
    """Hermetic twins: bridges and the pipeline resolve twins through app.twins.store.DEFAULT_PATH, so a test that
    does not opt in (``@pytest.mark.real_twins``, or patching DEFAULT_PATH itself) sees an empty map and never
    depends on which pairs the committed file happens to hold."""
    if request.node.get_closest_marker("real_twins"):
        yield
        return
    from app.twins import store

    monkeypatch.setattr(store, "DEFAULT_PATH", tmp_path / "no_twins.json")  # missing file = empty map
    yield


@pytest.fixture(autouse=True)
def _regular_session_wall_clock(monkeypatch):
    """Hermetic session for LIVE bridges: their closed-market mode reads the wall clock, so a test run on a weekend or
    at night would see equities closed (the equity algo holds). Pinned to a regular session (Wed 2026-09-30 11:00 ET)
    unless the test sets ``app.state.staged_clock``. Replays are unaffected: they use each tick's recorded time."""
    import datetime as dt

    from app.closed import bridge_mode

    monkeypatch.setattr(bridge_mode, "now_utc", lambda: dt.datetime(2026, 9, 30, 15, 0, tzinfo=dt.timezone.utc))
    yield


@pytest.fixture(autouse=True)
def _offline_liquidity(monkeypatch):
    """Hermetic liquidity data: no Massive client and no venue-book HTTP (a .env key must never reach the network
    from a test). Tests that exercise the liquidity numbers pin them (``service_for(app).set_equity`` or a fake)."""
    import httpx

    from app.liquidity import service

    def offline(request):
        raise httpx.ConnectError("offline test", request=request)

    monkeypatch.setattr(service, "make_client", lambda: None)
    monkeypatch.setattr(service, "default_http", lambda: httpx.AsyncClient(transport=httpx.MockTransport(offline)))
    yield


@pytest.fixture
def roomy_capital(monkeypatch):
    """For tests about broker mechanics, not capital: the capital check sees a $10M account with $10M buying power
    (the fake Webull sandboxes report a ~$100k account, on which the tests' 376-share shorts would rightly be
    refused). tests/test_capital.py covers the budget itself."""
    from app.capital import service

    async def snap(app, broker, refresh=False):
        return {"checked": True, "read_ok": True, "broker": getattr(broker, "name", None), "equity": 1e7,
                "cash": 1e7, "buying_power": 1e7, "short_notional": 0.0, "age_s": 0.0}
    monkeypatch.setattr(service, "account_snapshot", snap)
    yield
