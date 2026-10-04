import math

from polybridge_research.strategies import STRATEGIES, strategy_pnl

OTM = 0.05
M_E = {"C_K": 5.0, "C_U0.05": 2.0, "P_L0.05": 1.5}


def test_hand_computed_pnl_per_dollar_of_spot():
    m_x = {"C_K": 1.0, "C_U0.05": 0.2, "P_L0.05": 6.0}
    out = strategy_pnl(M_E, m_x, S_e=100.0, S_x=90.0, otm=OTM)
    assert set(out) == set(STRATEGIES)
    assert math.isclose(out["stock"], -0.10)
    assert math.isclose(out["long_call"], -0.04)
    assert math.isclose(out["covered_call"], -0.082)
    assert math.isclose(out["protective_put"], -0.055)
    assert math.isclose(out["collar"], -0.037)
    assert math.isclose(out["cash_secured_put"], -0.045)


def test_stale_leg_gives_nan_not_zero():
    m_x = {"C_K": 1.0, "C_U0.05": 0.2, "P_L0.05": float("nan")}
    out = strategy_pnl(M_E, m_x, S_e=100.0, S_x=90.0, otm=OTM)
    assert math.isnan(out["protective_put"])
    assert math.isnan(out["cash_secured_put"])
    assert math.isnan(out["collar"])
    assert math.isclose(out["long_call"], -0.04)
