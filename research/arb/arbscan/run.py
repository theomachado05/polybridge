from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ARB = HERE.parent
RESEARCH = ARB.parent
for p in (ARB, RESEARCH):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from polybridge_research.calendar import TradingCalendar  # noqa: E402
from polybridge_research.massive import MassiveClient, MissingApiKey, load_api_key  # noqa: E402

from arbscan import datasrc as ds  # noqa: E402
from arbscan.costs import KalshiFee, PolyFee, fee_from_gamma  # noqa: E402
from arbscan.parse import KALSHI_UNDERLYING, kalshi_is_close, parse_pm_question  # noqa: E402
from arbscan.score import score_row  # noqa: E402
from arbscan import verify as vf  # noqa: E402

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
SERIES_KALSHI = ["KXINXU", "KXNASDAQ100U", "INXU", "NASDAQ100U", "KXINXAB", "INXAB"]
KALSHI_TOP_PER_EVENT = 8
MIN_PM_HALF_SPREAD = 0.01
FALLBACK_HALF_SPREAD = 0.02


def et_dt(d: date, hh: int, mm: int) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=ET)


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def snapshot_meta(m: dict, snap_label: str, snap_dt: datetime, exp: str | None) -> dict:
    return dict(venue=m["venue"], market_id=m["id"], event=m["event"], question=m["question"], underlying=m["underlying"],
                series=m.get("series"), kind=m["kind"], res_date=m["res_date"].isoformat(), snapshot=snap_label,
                snap_utc=utc_iso(snap_dt), snap_epoch=snap_dt.timestamp(), expiry=exp,
                expiry_gap_days=(date.fromisoformat(exp) - m["res_date"]).days if exp else None, outcome=m.get("outcome"))


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def _jl(x) -> list:
    if isinstance(x, list):
        return x
    try:
        v = json.loads(x) if isinstance(x, str) else []
        return v if isinstance(v, list) else []
    except ValueError:
        return []


def _f(x):
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None


class Scan:
    def __init__(self, out: Path, cache: Path, start: str, end: str, workers: int = 6, limit: int | None = None):
        self.out, self.cache, self.start, self.end, self.workers, self.limit = out, cache, start, end, workers, limit
        self.now = datetime.now(UTC)
        self.today = self.now.astimezone(ET).date()
        self.cal = TradingCalendar()
        self.scope: Counter = Counter()
        self.http = ds.Http(cache / "http")
        try:
            key = load_api_key(search_from=RESEARCH.parent, interactive=False)
            self.massive = MassiveClient(key, cache_dir=cache / "massive", session=ds.CountingSession())
            self.opts = ds.OptionSource(self.massive, self.today)
        except MissingApiKey:
            self.massive, self.opts = None, None
        self.rows: list[dict] = []
        self.half_spread = FALLBACK_HALF_SPREAD
        self.half_spread_n = 0
        self.t0 = time.time()

    def pm_universe(self) -> list[dict]:
        events = ds.gamma_equity_events(self.http, f"{self.start}T00:00:00Z", f"{self.end}T23:59:59Z")
        self.scope["pm_events"] = len(events)
        out = []
        for ev in events:
            for m in ev.get("markets") or []:
                self.scope["pm_markets_seen"] += 1
                th, reason = parse_pm_question(m.get("question") or "", ev.get("title") or "")
                if th is None:
                    self.scope[f"pm_excluded_{reason}"] += 1
                    continue
                tokens = [str(t) for t in _jl(m.get("clobTokenIds"))]
                if not tokens or not m.get("endDate"):
                    self.scope["pm_excluded_no_token_or_date"] += 1
                    continue
                end_dt = _parse_iso(m["endDate"])
                prices = [str(x) for x in _jl(m.get("outcomePrices"))]
                outcome = 1 if prices[:2] == ["1", "0"] else 0 if prices[:2] == ["0", "1"] else None
                out.append(dict(venue="polymarket", id=str(m.get("id")), event=ev.get("slug"), question=m.get("question"),
                                underlying=th.ticker, strike=th.strike, kind=th.kind, end_dt=end_dt, cid=m.get("conditionId"),
                                res_date=end_dt.astimezone(ET).date(), token=tokens[0], closed=bool(m.get("closed")),
                                outcome=outcome if m.get("closed") else None, fee=fee_from_gamma(m),
                                start_dt=_parse_iso(m["startDate"]) if m.get("startDate") else None,
                                series=ev.get("seriesSlug")))
        self.scope["pm_in_scope"] = len(out)
        return out

    def kalshi_universe(self) -> tuple[list[dict], list[dict]]:
        hist, live = [], []
        min_ts = int(datetime.fromisoformat(self.start).replace(tzinfo=UTC).timestamp())
        for ser in SERIES_KALSHI:
            und = KALSHI_UNDERLYING[ser]
            fee = KalshiFee()
            for status in ("settled", "open"):
                ms = ds.kalshi_markets(self.http, ser, status, min_close_ts=min_ts if status == "settled" else None,
                                       max_close_ts=int(self.now.timestamp()) if status == "settled" else None)
                self.scope[f"kalshi_{ser}_{status}_markets"] = len(ms)
                by_event: dict[str, list[dict]] = {}
                for m in ms:
                    if not kalshi_is_close(m.get("event_ticker", "")):
                        self.scope["kalshi_excluded_not_1600_close"] += 1
                        continue
                    if m.get("strike_type") not in ("greater", "greater_or_equal") or m.get("floor_strike") is None:
                        self.scope["kalshi_excluded_not_above_threshold"] += 1
                        continue
                    by_event.setdefault(m["event_ticker"], []).append(m)
                for et_, lst in by_event.items():
                    if status == "settled":
                        lst = [x for x in lst if (_f(x.get("volume_fp")) or 0) > 0]
                        lst = sorted(lst, key=lambda x: -(_f(x.get("volume_fp")) or 0))[:KALSHI_TOP_PER_EVENT]
                    for m in lst:
                        close_dt = _parse_iso(m["close_time"])
                        rec = dict(venue="kalshi", id=m["ticker"], event=et_, question=m.get("title"), underlying=und,
                                   series=ser, strike=float(m["floor_strike"]), kind="hourly_close", end_dt=close_dt,
                                   res_date=close_dt.astimezone(ET).date(), closed=status == "settled",
                                   outcome={"yes": 1, "no": 0}.get(m.get("result")), fee=fee, raw=m)
                        (hist if status == "settled" else live).append(rec)
        self.scope["kalshi_hist_selected"] = len(hist)
        self.scope["kalshi_live_candidates"] = len(live)
        return hist, live

    def _option_context(self, m: dict) -> tuple[str | None, dict, bool, float | None]:
        ne = self.opts.nearest_expiry(m["underlying"], m["res_date"]) if self.opts else None
        if ne is None:
            return None, {}, False, None
        exp, chain = ne
        exp_d = date.fromisoformat(exp)
        return exp, chain, exp_d == m["res_date"], et_dt(exp_d, 16, 0).timestamp()

    def _row(self, m: dict, snap_label: str, snap_dt: datetime, pm: dict, live: bool) -> dict:
        exp, chain, clean, exp_close = self._option_context(m)
        meta = snapshot_meta(m, snap_label, snap_dt, exp)
        get_quote = lambda tk: self.opts.quote(tk, snap_dt) if self.opts else None  # noqa: E731
        return score_row(pm=pm, strike=m["strike"], chain=chain, get_quote=get_quote, snap_ts=snap_dt.timestamp(),
                         expiry_close_ts=exp_close, clean=clean, live=live, fee=m["fee"], meta=meta)

    def live_rows(self, pm_all: list[dict], kal_live: list[dict]) -> None:
        live_pm = [m for m in pm_all if not m["closed"] and m["end_dt"] > self.now]
        self.scope["pm_live_markets"] = len(live_pm)
        raw_dir = self.out / "raw_live"
        raw_dir.mkdir(parents=True, exist_ok=True)
        books = {}

        def get_book(m):
            return m["id"], ds.clob_book(self.http, m["token"])

        with ThreadPoolExecutor(self.workers) as ex:
            for mid, b in ex.map(get_book, live_pm):
                books[mid] = b
        pm_live_pm = []
        halves = []
        for m in live_pm:
            b = books.get(m["id"])
            if not b or not b["bids"] or not b["asks"]:
                self.scope["pm_live_no_two_sided_book"] += 1
                continue
            t = ds.book_touch(b)
            mid = (t["bid"] + t["ask"]) / 2
            if 0.02 <= mid <= 0.98:
                halves.append((t["ask"] - t["bid"]) / 2)
            pm_live_pm.append((m, dict(mid=mid, bid=t["bid"], ask=t["ask"], bid_size=t["bid_size"], ask_size=t["ask_size"], age_s=None)))
        if len(halves) >= 5:
            self.half_spread = max(MIN_PM_HALF_SPREAD, statistics.median(halves))
        self.half_spread_n = len(halves)
        (raw_dir / "polymarket_books.json").write_text(json.dumps(
            {"fetched_utc": self.now.isoformat(), "books": {m["id"]: {"q": m["question"], "book": books.get(m["id"])} for m in live_pm}}))
        kal_rows = []
        for m in kal_live:
            r = m["raw"]
            bid, ask = _f(r.get("yes_bid_dollars")), _f(r.get("yes_ask_dollars"))
            if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
                self.scope["kalshi_live_no_two_sided_book"] += 1
                continue
            kal_rows.append((m, dict(mid=(bid + ask) / 2, bid=bid, ask=ask, bid_size=_f(r.get("yes_bid_size_fp")),
                                     ask_size=_f(r.get("yes_ask_size_fp")), age_s=None)))
        (raw_dir / "kalshi_open.json").write_text(json.dumps(
            {"fetched_utc": self.now.isoformat(), "markets": [x[0]["raw"] for x in kal_rows]}))
        jobs = [(m, "LIVE", self.now, pm) for m, pm in pm_live_pm + kal_rows]
        self._run_jobs(jobs, live=True)

    def hist_rows_pm(self, pm_all: list[dict]) -> None:
        hist = [m for m in pm_all if m["end_dt"] <= self.now]
        self.scope["pm_resolved_or_ended"] = len(hist)
        if self.limit:
            hist = hist[: self.limit]
        windows = {}
        for m in hist:
            s1 = et_dt(self.cal.before(pd_ts(m["res_date"])).date(), 15, 45)
            s2 = et_dt(m["res_date"], 12, 0)
            windows[m["id"]] = (("S1", s1), ("S2", s2))

        def fetch(m):
            (_, s1), (_, s2) = windows[m["id"]]
            return m["id"], ds.clob_history(self.http, m["token"], int(s1.timestamp()) - 3600, int(s2.timestamp()) + 600, 1)

        histories = {}
        with ThreadPoolExecutor(self.workers) as ex:
            for mid, h in ex.map(fetch, hist):
                histories[mid] = h
        jobs = []
        h = self.half_spread
        for m in hist:
            for label, snap in windows[m["id"]]:
                if m["start_dt"] and snap < m["start_dt"]:
                    self.scope["pm_snapshot_before_listing"] += 1
                    continue
                pts = [(t, p) for t, p in histories.get(m["id"], []) if t <= snap.timestamp()]
                if not pts:
                    self.rows.append(dict(venue="polymarket", market_id=m["id"], event=m["event"], question=m["question"],
                                          underlying=m["underlying"], strike=m["strike"], snapshot=label, status="no_pm_price",
                                          label="not_scored", live=False, res_date=m["res_date"].isoformat(), outcome=m["outcome"]))
                    continue
                t, p = pts[-1]
                pm = dict(mid=p, bid=max(0.01, p - h), ask=min(0.99, p + h), bid_size=None, ask_size=None,
                          age_s=snap.timestamp() - t, spread_assumed=True)
                jobs.append((m, label, snap, pm))
        self._run_jobs(jobs, live=False)

    def hist_rows_kalshi(self, kal_hist: list[dict]) -> None:
        if self.limit:
            kal_hist = kal_hist[: self.limit]
        jobs = []

        def fetch(m):
            snap = et_dt(m["res_date"], 12, 0)
            c = ds.kalshi_candles(self.http, m["series"], m["id"], int(snap.timestamp()) - 1800, int(snap.timestamp()), 1)
            return m, snap, ds.kalshi_bid_ask_at(c, snap.timestamp())

        with ThreadPoolExecutor(self.workers) as ex:
            for m, snap, ba in ex.map(fetch, kal_hist):
                if ba is None:
                    self.scope["kalshi_no_bid_ask_candle"] += 1
                    self.rows.append(dict(venue="kalshi", market_id=m["id"], event=m["event"], question=m["question"],
                                          underlying=m["underlying"], strike=m["strike"], snapshot="S2", status="no_pm_price",
                                          label="not_scored", live=False, res_date=m["res_date"].isoformat(), outcome=m["outcome"]))
                    continue
                pm = dict(mid=(ba["bid"] + ba["ask"]) / 2, bid=ba["bid"], ask=ba["ask"], bid_size=None, ask_size=None,
                          age_s=snap.timestamp() - ba["t"], spread_assumed=False)
                jobs.append((m, "S2", snap, pm))
        self._run_jobs(jobs, live=False)

    def verify_stage(self, pm_all: list[dict]) -> None:
        byid = {m["id"]: m for m in pm_all}
        cand = [r for r in self.rows if r.get("venue") == "polymarket" and not r.get("live") and r.get("label") == "gap_robust"]
        cids = sorted({byid[r["market_id"]]["cid"] for r in cand if byid.get(r["market_id"], {}).get("cid")})
        self.scope["verify_candidates"] = len(cand)
        self.scope["verify_markets"] = len(cids)
        with ThreadPoolExecutor(self.workers) as ex:
            trades = dict(zip(cids, ex.map(lambda c: vf.fetch_trades(self.http, c), cids)))
        for r in cand:
            m = byid.get(r["market_id"], {})
            tr = trades.get(m.get("cid"), [])
            snap_ts = float(r["snap_epoch"])
            need = vf.needed_price(r["trade"], r["p_lo"], r["p_hi"], r["width"], m["fee"])
            r.update(verify_price_needed=need, verify_trades_in_market=len(tr), **vf.verify_row(tr, snap_ts, r["trade"], need))
            if r["verified"]:
                r["label"] = "gap_verified"
        for r in self.rows:
            if r.get("venue") == "kalshi" and not r.get("live") and r.get("label") == "gap_robust":
                r["label"] = "gap_verified"
        self.scope["verified_poly"] = sum(1 for r in cand if r.get("verified"))

    def _run_jobs(self, jobs: list, live: bool) -> None:
        def one(j):
            m, label, snap, pm = j
            try:
                return self._row(m, label, snap, pm, live)
            except Exception as e:
                self.scope["row_errors"] += 1
                self.http.failures.append(f"row-error {m['id']} {type(e).__name__}: {str(e)[:100]}")
                return None

        with ThreadPoolExecutor(self.workers) as ex:
            for r in ex.map(one, jobs):
                if r is not None:
                    self.rows.append(r)


def pd_ts(d: date):
    import pandas as pd
    return pd.Timestamp(d)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-08-15")
    ap.add_argument("--end", default="2026-10-12")
    ap.add_argument("--out", default=str(RESEARCH / "results" / "arb"))
    ap.add_argument("--cache", default=str(ARB / ".cache"))
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=None, help="debug: cap resolved markets per venue")
    ap.add_argument("--skip-kalshi", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    scan = Scan(out, Path(a.cache), a.start, a.end, a.workers, a.limit)
    if scan.opts is None:
        print("MASSIVE_API_KEY missing: no option data, nothing to score.", file=sys.stderr)
        return 0
    pm_all = scan.pm_universe()
    kal_hist, kal_live = ([], []) if a.skip_kalshi else scan.kalshi_universe()
    scan.live_rows(pm_all, kal_live)
    scan.hist_rows_pm(pm_all)
    scan.hist_rows_kalshi(kal_hist)
    scan.verify_stage(pm_all)
    import pandas as pd
    df = pd.DataFrame(scan.rows)
    df.to_csv(out / "arb_gaps.csv", index=False)
    meta = dict(now_utc=scan.now.isoformat(), start=a.start, end=a.end, half_spread=scan.half_spread,
                half_spread_n=scan.half_spread_n, scope=dict(scan.scope), seconds=time.time() - scan.t0,
                http={k: v for k, v in scan.http.session.counts.items()},
                massive_requests=dict(scan.massive.session.counts),
                failures=(scan.http.failures + scan.opts.failures)[:200], n_failures=len(scan.http.failures) + len(scan.opts.failures))
    (out / "run_meta.json").write_text(json.dumps(meta, indent=1, default=str))
    print(f"rows={len(df)} elapsed={meta['seconds']:.0f}s failures={meta['n_failures']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
