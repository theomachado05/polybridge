from __future__ import annotations

import numpy as np
import pandas as pd

from .calendar import TradingCalendar
from .config import StudyConfig
from .schema import STRATEGY_FOR_FAMILY, Family
from .stats import bootstrap_ci
from .strategies import STRATEGIES


DIFF_COLUMNS = ["strategy", "horizon", "n_a", "n_b", "mean_a", "mean_b", "difference", "ci_lo", "ci_hi", "p_value"]


def _horizons(cfg: StudyConfig, present) -> list:
    return [h for h in [*cfg.horizons, "exp"] if h in set(present)]


def slice_results(res: pd.DataFrame, bucket: str, entry: str, otm: float) -> pd.DataFrame:
    return res[(res.bucket == bucket) & (res.entry == entry) & (res.otm == otm)]


def scoreboard(res, cfg: StudyConfig, level: float = 0.95, bucket=None, entry=None, otm=None, horizons=None,
               strategies=STRATEGIES) -> pd.DataFrame:
    r = slice_results(res, bucket or cfg.baseline_bucket, entry or cfg.entry, otm or cfg.otm_pct)
    horizons = horizons or _horizons(cfg, r.horizon)
    rows = []
    for s in strategies:
        for h in horizons:
            x = r.loc[r.horizon == h, s].dropna()
            lo, hi = bootstrap_ci(x, level=level)
            rows.append({"strategy": s, "horizon": h, "n": len(x), "mean": x.mean(), "ci_lo": lo, "ci_hi": hi,
                         "median": x.median(), "hit_rate": (x > 0).mean() if len(x) else np.nan})
    return pd.DataFrame(rows)


def difference_board(res_a, res_b, cfg: StudyConfig, level: float = 0.95, column: str | None = None, entry=None,
                     bucket=None, otm=None, strategies=STRATEGIES, seed: int = 1, n_boot: int = 4000) -> pd.DataFrame:
    e = entry or cfg.entry
    a = slice_results(res_a, bucket or cfg.baseline_bucket, e, otm or cfg.otm_pct)
    b = slice_results(res_b, bucket or cfg.baseline_bucket, e, otm or cfg.otm_pct)
    cols = [column] if column else list(strategies)
    tail = (1 - level) / 2 * 100
    rng, rows = np.random.default_rng(seed), []
    for s in cols:
        for h in _horizons(cfg, set(a.horizon) & set(b.horizon)):
            xa = a.loc[a.horizon == h, s].dropna().to_numpy(float)
            xb = b.loc[b.horizon == h, s].dropna().to_numpy(float)
            row = {"strategy": s, "horizon": h, "n_a": len(xa), "n_b": len(xb)}
            if len(xa) >= 5 and len(xb) >= 5:
                d = rng.choice(xa, (n_boot, len(xa))).mean(1) - rng.choice(xb, (n_boot, len(xb))).mean(1)
                p = 2 * min((d <= 0).mean(), (d >= 0).mean())
                row.update(mean_a=xa.mean(), mean_b=xb.mean(), difference=xa.mean() - xb.mean(),
                           ci_lo=np.percentile(d, tail), ci_hi=np.percentile(d, 100 - tail), p_value=max(p, 1 / n_boot))
            rows.append(row)
    return pd.DataFrame(rows, columns=DIFF_COLUMNS)


def sample_placebo(events: pd.DataFrame, n: int, start: str, end: str, cal: TradingCalendar, gap_days: int,
                   seed: int = 7, last_session=None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    stop = pd.Timestamp(end) if last_session is None else min(pd.Timestamp(end), pd.Timestamp(last_session))
    sessions = cal.sessions[(cal.sessions >= pd.Timestamp(start)) & (cal.sessions <= stop)]
    cols = ["ticker", "filing_date", "t_0", "t_pre"] + (["family"] if "family" in events else [])
    if events.empty or len(sessions) == 0:
        return pd.DataFrame(columns=cols)
    by_ticker = events.groupby("ticker")["filing_date"].apply(list)
    fam = events.groupby("ticker")["family"].first() if "family" in events else None
    rows = []
    for t in rng.choice(events["ticker"].to_numpy(), size=n, replace=True):
        for _ in range(50):
            d = sessions[rng.integers(len(sessions))]
            if all(abs((d - a).days) > gap_days for a in by_ticker.get(t, [])):
                row = {"ticker": t, "filing_date": d, "t_0": d, "t_pre": cal.before(d)}
                if fam is not None:
                    row["family"] = fam[t]
                rows.append(row)
                break
    return pd.DataFrame(rows, columns=cols)


def decay_table(res: pd.DataFrame, cfg: StudyConfig, entry: str = "pre") -> pd.DataFrame:
    r = slice_results(res, cfg.baseline_bucket, entry, cfg.otm_pct)
    rows = []
    for h in _horizons(cfg, r.horizon):
        x = r.loc[r.horizon == h, "ratio"].dropna()
        lo, hi = bootstrap_ci(x)
        rows.append({"horizon": h, "n": len(x), "mean_ratio": x.mean(), "ci_lo": lo, "ci_hi": hi,
                     "median_ratio": x.median(), "share_above_1": (x > 1).mean() if len(x) else np.nan})
    return pd.DataFrame(rows).set_index("horizon") if rows else pd.DataFrame(
        columns=["n", "mean_ratio", "ci_lo", "ci_hi", "median_ratio", "share_above_1"])


def with_put_leg(res: pd.DataFrame) -> pd.DataFrame:
    return res.assign(put_leg=res["protective_put"] - res["stock"]) if len(res) else res.assign(put_leg=pd.Series(dtype=float))


def _cluster_means(x: np.ndarray, groups: np.ndarray, rng, n_boot: int) -> np.ndarray:
    keys, inv = np.unique(groups, return_inverse=True)
    sums = np.bincount(inv, weights=x, minlength=len(keys))
    counts = np.bincount(inv, minlength=len(keys)).astype(float)
    draw = rng.integers(len(keys), size=(n_boot, len(keys)))
    return sums[draw].sum(1) / counts[draw].sum(1)


def cluster_difference_board(res_a, res_b, cfg: StudyConfig, column: str, level: float = 0.95, entry=None,
                             cluster: str = "ticker", seed: int = 1, n_boot: int = 4000) -> pd.DataFrame:
    e = entry or cfg.entry
    a = slice_results(res_a, cfg.baseline_bucket, e, cfg.otm_pct)
    b = slice_results(res_b, cfg.baseline_bucket, e, cfg.otm_pct)
    tail = (1 - level) / 2 * 100
    rng, rows = np.random.default_rng(seed), []
    for h in _horizons(cfg, set(a.horizon) & set(b.horizon)):
        da = a.loc[a.horizon == h, [column, cluster]].dropna()
        db = b.loc[b.horizon == h, [column, cluster]].dropna()
        row = {"strategy": column, "horizon": h, "n_a": len(da), "n_b": len(db)}
        if len(da) >= 5 and len(db) >= 5 and da[cluster].nunique() >= 2 and db[cluster].nunique() >= 2:
            d = (_cluster_means(da[column].to_numpy(float), da[cluster].to_numpy(), rng, n_boot)
                 - _cluster_means(db[column].to_numpy(float), db[cluster].to_numpy(), rng, n_boot))
            p = 2 * min((d <= 0).mean(), (d >= 0).mean())
            row.update(mean_a=da[column].mean(), mean_b=db[column].mean(), difference=da[column].mean() - db[column].mean(),
                       ci_lo=np.percentile(d, tail), ci_hi=np.percentile(d, 100 - tail), p_value=max(p, 1 / n_boot))
        rows.append(row)
    return pd.DataFrame(rows, columns=DIFF_COLUMNS)


def robustness_table(events_res, placebo_res, family: str, cfg: StudyConfig) -> pd.DataFrame:
    strategy = STRATEGY_FOR_FAMILY[Family(family)]
    ev, pl = with_put_leg(events_res), with_put_leg(placebo_res)
    level, heads = cfg.confirmatory_level, list(cfg.headline_horizons)
    boards = [("pre-registered (iid)", difference_board(ev, pl, cfg, level=level, strategies=[strategy])),
              ("company-clustered", cluster_difference_board(ev, pl, cfg, strategy, level=level))]
    if family == Family.HEDGE.value:
        boards += [("put leg only (iid)", difference_board(ev, pl, cfg, level=level, column="put_leg")),
                   ("put leg only, company-clustered", cluster_difference_board(ev, pl, cfg, "put_leg", level=level))]
    out = [b[b.horizon.isin(heads)].assign(check=name) for name, b in boards]
    t = pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=[*DIFF_COLUMNS, "check"])
    return t.rename(columns={"strategy": "measure", "n_a": "n_events", "n_b": "n_placebo", "difference": "edge"})[
        ["check", "measure", "horizon", "n_events", "n_placebo", "edge", "ci_lo", "ci_hi"]]


def verdict(chk: dict | None) -> str:
    if chk is None:
        return "INSUFFICIENT"
    if chk["passed"]:
        return "PASS"
    testable = chk["pnl"]["ci_lo"].notna().sum() if len(chk["pnl"]) else 0
    return "NULL" if testable >= 2 else "INSUFFICIENT"


def pass_check(events_res, placebo_res, family: str, cfg: StudyConfig) -> dict:
    strategy = STRATEGY_FOR_FAMILY[Family(family)]
    heads = list(cfg.headline_horizons)
    pnl = difference_board(events_res, placebo_res, cfg, level=cfg.confirmatory_level, strategies=[strategy])
    pnl = pnl[pnl.horizon.isin(heads)].reset_index(drop=True)
    ratio = difference_board(events_res, placebo_res, cfg, level=cfg.confirmatory_level, column="ratio", entry="pre")
    ratio = ratio[ratio.horizon.isin(heads)].reset_index(drop=True)
    want_up = family == Family.HEDGE.value
    pnl_ok = [h for h in heads if ((pnl["horizon"] == h) & (pnl["ci_lo"] > 0)).any()]
    d = ratio["difference"]
    sign_ok = (d > 0) if want_up else (d < 0)
    ratio_ok = [h for h in heads if ((ratio["horizon"] == h) & sign_ok).any()]
    both = [h for h in heads if h in pnl_ok and h in ratio_ok]
    return {"family": family, "strategy": strategy, "pnl": pnl, "ratio": ratio,
            "horizons_pnl_ok": pnl_ok, "horizons_ratio_ok": ratio_ok, "passed": len(both) >= 2}
