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
