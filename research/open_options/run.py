from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
for p in (RESEARCH, RESEARCH / "arb"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import open_options  # noqa: E402,F401  (puts research/arb on sys.path)
from arbscan import datasrc as ds  # noqa: E402
from arbscan import verify as vf  # noqa: E402
from arbscan.costs import KalshiFee, fee_from_gamma  # noqa: E402
from arbscan.parse import KALSHI_UNDERLYING, kalshi_is_close, parse_pm_question  # noqa: E402
from polybridge_research.massive import MassiveClient, MissingApiKey, load_api_key  # noqa: E402

from open_options import measure as ms  # noqa: E402
from open_options.closures import ET, Closure, build_closures, eligible, et  # noqa: E402

UTC = timezone.utc
END_MIN, END_MAX = "2025-10-01", "2026-10-12"
SERIES_KALSHI = ["KXINXU", "KXNASDAQ100U", "INXU", "NASDAQ100U", "KXINXAB", "INXAB"]


def _iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def _jl(x) -> list:
    if isinstance(x, list):
        return x
    try:
        v = json.loads(x) if isinstance(x, str) else []
        return v if isinstance(v, list) else []
    except ValueError:
        return []


class Study:
    def __init__(self, out: Path, cache: Path, workers: int = 8):
        self.out, self.workers = out, workers
        self.scope: Counter = Counter()
        self.http = ds.Http(cache / "http")
        key = load_api_key(search_from=RESEARCH.parent, interactive=False)
        self.massive = MassiveClient(key, cache_dir=cache / "massive", session=ds.CountingSession())
        self.opts = ds.OptionSource(self.massive, datetime.now(ET).date())
        self.closures = build_closures()
        self.t0 = time.time()

    def polymarket(self) -> list[dict]:
        events, d0, d1 = {}, date.fromisoformat(END_MIN), date.fromisoformat(END_MAX)
        while d0 <= d1:
            e = min(d0 + timedelta(days=13), d1)
            n_fail = len(self.http.failures)
            chunk = ds.gamma_equity_events(self.http, f"{d0}T00:00:00Z", f"{e}T23:59:59Z")
            if len(self.http.failures) > n_fail:
                self.scope["gamma_chunk_failures"] += 1
            for ev in chunk:
                events[str(ev.get("id"))] = ev
            d0 = e + timedelta(days=1)
        events = list(events.values())
        self.scope["pm_events"] = len(events)
        out = []
        for ev in events:
            for m in ev.get("markets") or []:
                self.scope["pm_markets_seen"] += 1
                th, why = parse_pm_question(m.get("question") or "", ev.get("title") or "")
                if th is None:
                    self.scope[f"pm_excluded_{why}"] += 1
                    continue
                tok = [str(t) for t in _jl(m.get("clobTokenIds"))]
                if not tok or not m.get("endDate"):
                    self.scope["pm_excluded_no_token_or_date"] += 1
                    continue
                end = _iso(m["endDate"])
                prices = [str(x) for x in _jl(m.get("outcomePrices"))]
                outcome = 1 if prices[:2] == ["1", "0"] else 0 if prices[:2] == ["0", "1"] else None
                out.append(dict(venue="polymarket", id=str(m.get("id")), question=m.get("question"), underlying=th.ticker,
                                strike=th.strike, kind=th.kind, end=end, res_date=end.astimezone(ET).date(), token=tok[0],
                                cid=m.get("conditionId"), listed=_iso(m["startDate"]) if m.get("startDate") else None,
                                outcome=outcome if m.get("closed") else None, fee=fee_from_gamma(m)))
        self.scope["pm_in_scope"] = len(out)
        return out

    def kalshi(self) -> list[dict]:
        out = []
        lo = int(datetime.fromisoformat(END_MIN).replace(tzinfo=UTC).timestamp())
        hi = int(datetime.now(UTC).timestamp())
        for ser in SERIES_KALSHI:
            ms_ = ds.kalshi_markets(self.http, ser, "settled", min_close_ts=lo, max_close_ts=hi)
            self.scope[f"kalshi_{ser}_settled"] = len(ms_)
            for m in ms_:
                if not kalshi_is_close(m.get("event_ticker", "")):
                    self.scope["kalshi_excluded_not_1600"] += 1
                    continue
                if m.get("strike_type") not in ("greater", "greater_or_equal") or m.get("floor_strike") is None:
                    self.scope["kalshi_excluded_not_above"] += 1
                    continue
                end = _iso(m["close_time"])
                out.append(dict(venue="kalshi", id=m["ticker"], question=m.get("title"), underlying=KALSHI_UNDERLYING[ser],
                                series=ser, strike=float(m["floor_strike"]), kind="kalshi_1600", end=end,
                                res_date=end.astimezone(ET).date(), listed=_iso(m["open_time"]) if m.get("open_time") else None,
                                outcome={"yes": 1, "no": 0}.get(m.get("result")), fee=KalshiFee()))
        self.scope["kalshi_in_scope"] = len(out)
        return out

    def pairs(self, markets: list[dict]) -> list[tuple[dict, Closure]]:
        out = []
        for m in markets:
            for c in self.closures:
                if c.close >= m["end"] or (m["listed"] and c.eod < m["listed"]):
                    continue
                why = eligible(c, m["listed"], m["end"], m["res_date"])
                if why:
                    self.scope[f"pair_{why}"] += 1
                    continue
                out.append((m, c))
        self.scope["pairs_life_ok"] = len(out)
        keys = sorted({(m["underlying"], m["res_date"].isoformat()) for m, _ in out})
        with ThreadPoolExecutor(self.workers) as ex:
            chains = dict(zip(keys, ex.map(lambda k: self.opts.contracts(*k), keys)))
        self.chains = chains
        ok = []
        for m, c in out:
            if chains.get((m["underlying"], m["res_date"].isoformat())):
                ok.append((m, c))
            else:
                self.scope["pair_no_clean_expiry"] += 1
        self.scope["pairs_eligible"] = len(ok)
        return ok

    def _pm_points(self, m: dict, t0: datetime, t1: datetime) -> list[tuple[float, float]] | list[dict]:
        if m["venue"] == "polymarket":
            return ds.clob_history(self.http, m["token"], int(t0.timestamp()), int(t1.timestamp()), 1)
        return ds.kalshi_candles(self.http, m["series"], m["id"], int(t0.timestamp()), int(t1.timestamp()), 1)

    def pm_value(self, m: dict, pts, at: datetime) -> float | None:
        if m["venue"] == "polymarket":
            return ms.pm_at(pts, at.timestamp())
        return ms.kalshi_mid_at(pts, at.timestamp())

    def pm_stage(self, pairs) -> list[dict]:
        def one(mc):
            m, c = mc
            a = self._pm_points(m, c.close - timedelta(minutes=60), c.close + timedelta(minutes=1))
            b = self._pm_points(m, c.open - timedelta(minutes=60), c.opt_open + timedelta(minutes=1))
            return dict(m=m, c=c, pm_close=self.pm_value(m, a, c.close), pm_open=self.pm_value(m, b, c.open),
                        pm_0945=self.pm_value(m, b, c.opt_open))

        with ThreadPoolExecutor(self.workers) as ex:
            rows = list(ex.map(one, pairs))
        for r in rows:
            r["status"] = ms.pm_filter(r["pm_close"], r["pm_open"])
            self.scope[f"status_{r['status'] or 'pass_f1_f3'}"] += 1
        return rows

    def _q(self, ticker: str, ts: float):
        return self.opts.quote(ticker, datetime.fromtimestamp(ts, UTC))

    def opt_stage(self, rows: list[dict]) -> None:
        todo = [r for r in rows if not r["status"]]

        def one(r):
            m, c = r["m"], r["c"]
            chain = self.chains[(m["underlying"], m["res_date"].isoformat())]
            exp_close = et(m["res_date"], 16, 0).timestamp()
            k = m["strike"]
            oc = ms.spread_at(chain, k, self._q, c.opt_close.timestamp(), exp_close)
            oo = ms.spread_at(chain, k, self._q, c.opt_open.timestamp(), exp_close, max_age=ms.OPEN_MAX_AGE,
                              floor_ts=c.open.timestamp())
            r.update(oc=oc, oo=oo, status=ms.opt_filter(oc, oo))
            if r["status"]:
                return r
            r["oc_w"] = ms.spread_at(chain, k, self._q, c.opt_close.timestamp(), exp_close, extra=1)
            r["oo_w"] = ms.spread_at(chain, k, self._q, c.opt_open.timestamp(), exp_close, max_age=ms.OPEN_MAX_AGE,
                                     floor_ts=c.open.timestamp(), extra=1)
            r["oe"] = ms.spread_at(chain, k, self._q, c.opt_eod.timestamp(), exp_close, pair=(oo.k1, oo.k2))
            pts = self._pm_points(m, c.eod - timedelta(minutes=60), c.eod + timedelta(minutes=1))
            r["pm_eod"] = self.pm_value(m, pts, c.eod)
            return r

        with ThreadPoolExecutor(self.workers) as ex:
            list(ex.map(one, todo))
        for r in todo:
            self.scope[f"status_{r['status'] or 'event'}"] += 1

    def prints_stage(self, rows: list[dict]) -> None:
        ev = [r for r in rows if r.get("status") == "" and r["m"]["venue"] == "polymarket" and r["m"].get("cid")]
        cids = sorted({r["m"]["cid"] for r in ev})
        with ThreadPoolExecutor(2) as ex:
            trades = dict(zip(cids, ex.map(lambda c: vf.fetch_trades(self.http, c), cids)))
        for r in ev:
            c = r["c"]
            r["prints_in_closure"] = ms.trade_prints_in(trades.get(r["m"]["cid"], []), c.close.timestamp(), c.open.timestamp())

    @staticmethod
    def flat(r: dict) -> dict:
        m, c = r["m"], r["c"]
        row = dict(venue=m["venue"], market_id=m["id"], question=m["question"], underlying=m["underlying"], strike=m["strike"],
                   kind=m["kind"], res_date=m["res_date"].isoformat(), outcome=m.get("outcome"), closure=c.key,
                   open_day=c.open_day.isoformat(), closure_kind=c.kind, status=r["status"] or "event",
                   pm_close=r.get("pm_close"), pm_open=r.get("pm_open"), pm_0945=r.get("pm_0945"), pm_eod=r.get("pm_eod"),
                   prints_in_closure=r.get("prints_in_closure"))
        for tag in ("oc", "oo", "oe", "oc_w", "oo_w"):
            sp = r.get(tag)
            if sp is not None:
                row.update({f"{tag}_k1": sp.k1, f"{tag}_k2": sp.k2, f"{tag}_mid": sp.p_mid, f"{tag}_lo": sp.p_lo,
                            f"{tag}_hi": sp.p_hi})
                if tag in ("oc", "oo"):
                    row[f"{tag}_stepped"] = sp.stepped
                    q_ts = min(sp.q1.ts, sp.q2.ts)
                    row[f"{tag}_quote_age_s"] = {"oc": r["c"].opt_close, "oo": r["c"].opt_open}[tag].timestamp() - q_ts
        if r["status"] == "":
            row.update(ms.event_metrics(r["pm_close"], r["pm_open"], r["oc"], r["oo"]))
            row.update(ms.follow_through(row["s"], r["oo"], r.get("oe"), r["pm_open"], r.get("pm_eod")))
            row["same_pair"] = (r["oc"].k1, r["oc"].k2) == (r["oo"].k1, r["oo"].k2)
            ws = [abs(r[n].p_mid - r[w].p_mid) for n, w in (("oc", "oc_w"), ("oo", "oo_w")) if r.get(w) is not None]
            row["width_sens_max"] = max(ws) if len(ws) == 2 else None
        return row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(RESEARCH / "results" / "open_options"))
    ap.add_argument("--cache", default=str(HERE / ".cache"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--skip-kalshi", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        st = Study(out, Path(a.cache), a.workers)
    except MissingApiKey:
        print("MASSIVE_API_KEY missing", file=sys.stderr)
        return 1
    st.scope["closures"] = len(st.closures)
    markets = st.polymarket() + ([] if a.skip_kalshi else st.kalshi())
    print(f"markets={len(markets)} t={time.time() - st.t0:.0f}s", flush=True)
    pairs = st.pairs(markets)
    print(f"eligible pairs={len(pairs)} t={time.time() - st.t0:.0f}s", flush=True)
    rows = st.pm_stage(pairs)
    print(f"pm stage done, pass f1-f3={sum(1 for r in rows if not r['status'])} t={time.time() - st.t0:.0f}s", flush=True)
    st.opt_stage(rows)
    st.prints_stage(rows)
    import pandas as pd
    df = pd.DataFrame([Study.flat(r) for r in rows])
    df.to_csv(out / "events.csv", index=False)
    meta = dict(run_utc=datetime.now(UTC).isoformat(), seconds=round(time.time() - st.t0), scope=dict(st.scope),
                http=dict(st.http.session.counts), massive_requests=dict(st.massive.session.counts),
                failures=(st.http.failures + st.opts.failures)[:200], n_failures=len(st.http.failures) + len(st.opts.failures),
                argv=sys.argv[1:])
    (out / "run_meta.json").write_text(json.dumps(meta, indent=1, default=str))
    print(f"rows={len(df)} events={(df.status == 'event').sum() if len(df) else 0} failures={meta['n_failures']} "
          f"t={meta['seconds']}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
