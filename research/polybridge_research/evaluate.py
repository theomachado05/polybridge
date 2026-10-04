from __future__ import annotations

import numpy as np
import pandas as pd

from .calendar import TradingCalendar
from .config import StudyConfig
from .parity import implied_scaled
from .strategies import STRATEGIES, strategy_pnl

COLUMNS = ["ticker", "family", "event_date", "t_0", "bucket", "expiry", "entry", "entry_date", "horizon", "exit_date",
           "sessions_held", "dte_sessions", "S_entry", "S_exit", "realized", "implied_move", "implied_scaled", "otm",
           *STRATEGIES, "ratio"]


def evaluate(priced, cal: TradingCalendar, cfg: StudyConfig, last_session: pd.Timestamp) -> pd.DataFrame:
    rows = []
    for pe in priced:
        exits = {0: pe.t_0}
        for h in cfg.horizons:
            d = cal.offset(pe.t_0, h)
            if d is not None and d <= pe.expiry_session:
                exits[h] = d
        exits["exp"] = pe.expiry_session
        for entry, e_day in (("pre", pe.t_pre), ("post", pe.t_0)):
            m_e = pe.marks(e_day)
            S_e = pe.synthetic_spot(e_day, m_e)
            if np.isnan(S_e):
                continue
            implied = (m_e["C_K"] + m_e["P_K"]) / S_e
            dte_sessions = cal.between(e_day, pe.expiry_session)
            for h, x_day in exits.items():
                if x_day > last_session:
                    continue
                m_x = pe.marks(x_day)
                S_x = pe.synthetic_spot(x_day, m_x)
                held = cal.between(e_day, x_day)
                base = {"ticker": pe.ticker, "family": pe.family, "event_date": pe.event_date, "t_0": pe.t_0,
                        "bucket": pe.bucket, "expiry": pe.expiry, "entry": entry, "entry_date": e_day, "horizon": h,
                        "exit_date": x_day, "sessions_held": held, "dte_sessions": dte_sessions, "S_entry": S_e,
                        "S_exit": S_x, "realized": S_x / S_e - 1, "implied_move": implied,
                        "implied_scaled": implied_scaled(implied, held, dte_sessions)}
                for otm in cfg.otm_grid:
                    rows.append(dict(base, otm=otm, **strategy_pnl(m_e, m_x, S_e, S_x, otm)))
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    res = pd.DataFrame(rows)
    res["ratio"] = res["realized"].abs() / res["implied_scaled"]
    return res[COLUMNS]
