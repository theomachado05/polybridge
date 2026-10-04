from __future__ import annotations

STRATEGIES = ["stock", "long_call", "covered_call", "protective_put", "collar", "cash_secured_put"]


def strategy_pnl(m_e: dict[str, float], m_x: dict[str, float], S_e: float, S_x: float, otm: float) -> dict[str, float]:
    dS = S_x - S_e
    dC_U = m_x[f"C_U{otm}"] - m_e[f"C_U{otm}"]
    dP_L = m_x[f"P_L{otm}"] - m_e[f"P_L{otm}"]
    dC_K = m_x["C_K"] - m_e["C_K"]
    return {
        "stock": dS / S_e,
        "long_call": dC_K / S_e,
        "covered_call": (dS - dC_U) / S_e,
        "protective_put": (dS + dP_L) / S_e,
        "collar": (dS + dP_L - dC_U) / S_e,
        "cash_secured_put": (-dP_L) / S_e,
    }
