"""Remote (tunnelled) writes need X-Agent-Secret; local use (browser on localhost, tests) is unchanged."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.security import _host_name

TUNNEL = {"x-forwarded-for": "203.0.113.9", "host": "abc123.ngrok-free.app"}


@pytest.fixture
def c():
    with TestClient(create_app()) as client:
        yield client


@pytest.mark.parametrize("method,path,body", [
    ("post", "/orders", {"symbol": "SPY", "asset": "equity", "side": "buy", "qty": 10000, "ref_px": 0.01}),
    ("post", "/account/reset", None), ("delete", "/orders/x", None), ("post", "/proposals/p1/approve", None),
    ("post", "/bridges", {"proposal_id": "p1", "source": "replay"}), ("post", "/agent/tool/account", {})])
def test_tunnelled_writes_are_refused_without_the_secret(c, monkeypatch, method, path, body):
    monkeypatch.delenv("AGENT_TOOL_SECRET", raising=False)
    kw = {"json": body} if body is not None else {}
    r = getattr(c, method)(path, headers=TUNNEL, **kw)
    assert r.status_code == 401 and "AGENT_TOOL_SECRET" in r.json()["detail"]
    monkeypatch.setenv("AGENT_TOOL_SECRET", "s3")
    assert getattr(c, method)(path, headers={**TUNNEL, "x-agent-secret": "nope"}, **kw).status_code == 401


def test_tunnelled_reads_and_the_secret_holder_still_work(c, monkeypatch):
    monkeypatch.setenv("AGENT_TOOL_SECRET", "s3")
    assert c.get("/agent/tools", headers=TUNNEL).status_code == 200
    assert c.get("/account", headers=TUNNEL).status_code == 200
    assert c.post("/agent/tool/account", json={}, headers={**TUNNEL, "x-agent-secret": "s3"}).status_code == 200


def test_a_cloudflare_or_plain_host_header_counts_as_remote(c, monkeypatch):
    monkeypatch.delenv("AGENT_TOOL_SECRET", raising=False)
    assert c.post("/account/reset", headers={"cf-connecting-ip": "1.2.3.4"}).status_code == 401
    assert c.post("/account/reset", headers={"host": "my-tunnel.trycloudflare.com"}).status_code == 401
    assert c.post("/account/reset").status_code == 200  # local: unchanged


def test_remote_order_with_the_secret_cannot_choose_its_fill_price(c, monkeypatch):
    monkeypatch.setenv("AGENT_TOOL_SECRET", "s3")
    r = c.post("/orders", json={"symbol": "SPY", "asset": "equity", "side": "buy", "qty": 10, "ref_px": 0.01},
               headers={**TUNNEL, "x-agent-secret": "s3"})
    assert r.status_code == 422 and "no_price" in r.json()["detail"]  # ref_px dropped; tests have no quote source


def test_host_name_parsing():
    assert _host_name("localhost:8000") == "localhost" and _host_name("[::1]:8000") == "[::1]"
    assert _host_name("127.0.0.1") == "127.0.0.1" and _host_name("abc.ngrok-free.app") == "abc.ngrok-free.app"
