"""The five library strategies plus the stock reference, as P&L per $1 of spot at entry.

Identical to the Massive starter, section 6: the stock leg is the synthetic long (ATM call - ATM put).
A NaN mark (a leg too stale to price) propagates to NaN P&L; it is never treated as zero.
"""
from __future__ import annotations

STRATEGIES = ["stock", "long_call", "covered_call", "protective_put", "collar", "cash_secured_put"]


def strategy_pnl(m_e: dict[str, float], m_x: dict[str, float], S_e: float, S_x: float, otm: float) -> dict[str, float]:
    dS = S_x - S_e
    dC_U = m_x[f"C_U{otm}"] - m_e[f"C_U{otm}"]   # the OTM call we sell
    dP_L = m_x[f"P_L{otm}"] - m_e[f"P_L{otm}"]   # the OTM put we buy (or sell, cash-secured)
    dC_K = m_x["C_K"] - m_e["C_K"]               # the ATM call we buy
    return {
        "stock": dS / S_e,
        "long_call": dC_K / S_e,
        "covered_call": (dS - dC_U) / S_e,
        "protective_put": (dS + dP_L) / S_e,
        "collar": (dS + dP_L - dC_U) / S_e,
        "cash_secured_put": (-dP_L) / S_e,
    }
