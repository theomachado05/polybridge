import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parents[2] / "research" / "tests" / "fakes.py"
_spec = importlib.util.spec_from_file_location("research_fakes", _path)
research_fakes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(research_fakes)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_broker(tmp_path, monkeypatch):
    import app.broker as broker

    monkeypatch.setenv("SIM_ACCOUNT_PATH", str(tmp_path / "sim_account.json"))
    monkeypatch.setenv("BROKER", "sim")
    monkeypatch.setattr(broker, "_quotes", lambda app: broker.NullQuotes())
    broker.reset_default_broker()
    yield
    broker.reset_default_broker()


@pytest.fixture(autouse=True)
def _no_llm_keys(monkeypatch):
    from app.pipeline import llm

    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setattr(llm, "gemini_key", lambda: None)
    llm._models_cache.clear()
    llm._resolved.clear()
    yield
    llm._models_cache.clear()
    llm._resolved.clear()


def pytest_configure(config):
    config.addinivalue_line("markers", "real_twins: read the committed twin map (app/data/kalshi_twins.json) "
                                       "instead of the empty map every other test gets")


@pytest.fixture(autouse=True)
def _empty_twin_map(request, tmp_path, monkeypatch):
    if request.node.get_closest_marker("real_twins"):
        yield
        return
    from app.twins import store

    monkeypatch.setattr(store, "DEFAULT_PATH", tmp_path / "no_twins.json")
    yield


@pytest.fixture(autouse=True)
def _regular_session_wall_clock(monkeypatch):
    import datetime as dt

    from app.closed import bridge_mode

    monkeypatch.setattr(bridge_mode, "now_utc", lambda: dt.datetime(2026, 9, 30, 15, 0, tzinfo=dt.timezone.utc))
    yield


@pytest.fixture(autouse=True)
def _offline_liquidity(monkeypatch):
    import httpx

    from app.liquidity import service

    def offline(request):
        raise httpx.ConnectError("offline test", request=request)

    monkeypatch.setattr(service, "make_client", lambda: None)
    monkeypatch.setattr(service, "default_http", lambda: httpx.AsyncClient(transport=httpx.MockTransport(offline)))
    yield


@pytest.fixture
def roomy_capital(monkeypatch):
    from app.capital import service

    async def snap(app, broker, refresh=False):
        return {"checked": True, "read_ok": True, "broker": getattr(broker, "name", None), "equity": 1e7,
                "cash": 1e7, "buying_power": 1e7, "short_notional": 0.0, "age_s": 0.0}
    monkeypatch.setattr(service, "account_snapshot", snap)
    yield


@pytest.fixture(autouse=True)
def _no_gemini_retry_sleep(monkeypatch):
    from app.pipeline import llm
    monkeypatch.setattr(llm, "RETRY_ATTEMPTS", 1)


@pytest.fixture(autouse=True)
def _hermetic_gemini_model(monkeypatch):
    from app.pipeline import llm
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setattr(llm, "DEFAULT_MODEL", "gemini-2.5-flash")
