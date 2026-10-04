import pandas as pd
import pytest

from polybridge_research.book import metrics


def test_metrics_drawdown_sharpe_and_turnover():
    t = pd.DataFrame({"net": [0.02, -0.03, 0.01, 0.04]})
    m = metrics(t, years=1.0, horizon_sessions=21)
    assert m["trades"] == 4
    assert m["max_drawdown_pct"] == pytest.approx(-3.0)
    assert m["total_net_pct"] == pytest.approx(4.0)
    assert m["avg_open_positions"] == pytest.approx(4 * 21 / 252)
    assert m["turnover_x_per_year"] == pytest.approx(12.0)
    x = t["net"]
    assert m["sharpe_net"] == pytest.approx(x.mean() / x.std(ddof=1) * 2.0)


def test_metrics_override_rate_and_empty():
    t = pd.DataFrame({"net": [0.01, 0.02, -0.01]})
    assert metrics(t, years=1.0, per_year=12.0)["trades_per_year"] == 12.0
    assert metrics(t.iloc[0:0], years=1.0) == {"trades": 0}


def test_drawdown_counts_a_first_trade_loss():
    m = metrics(pd.DataFrame({"net": [-0.05, 0.01, 0.01]}), years=1.0)
    assert m["max_drawdown_pct"] == pytest.approx(-5.0)
