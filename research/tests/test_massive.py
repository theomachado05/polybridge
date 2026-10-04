import json

import pytest
import requests

from polybridge_research.massive import MassiveClient, MissingApiKey, load_api_key


class FakeResponse:
    def __init__(self, status: int, payload: dict | None = None, headers: dict | None = None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []
        self.headers = {}

    def get(self, url, timeout):
        self.urls.append(url)
        return self.responses.pop(0)


def test_key_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("MASSIVE_API_KEY", "  abc123 ")
    assert load_api_key(search_from=tmp_path, interactive=False) == "abc123"


def test_key_from_dotenv_in_parent(monkeypatch, tmp_path):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    (tmp_path / ".env").write_text('MASSIVE_API_KEY="fromfile"\n')
    child = tmp_path / "research"
    child.mkdir()
    assert load_api_key(search_from=child, interactive=False) == "fromfile"


def test_placeholder_key_counts_as_missing_and_never_prompts(monkeypatch, tmp_path):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    (tmp_path / ".env").write_text("MASSIVE_API_KEY=your-key-here\n")
    with pytest.raises(MissingApiKey, match="MASSIVE_API_KEY"):
        load_api_key(search_from=tmp_path, interactive=False)


def test_get_caches_by_full_url(tmp_path):
    session = FakeSession([FakeResponse(200, {"results": [1]})])
    client = MassiveClient("k", cache_dir=tmp_path, session=session, sleep=lambda s: None)
    assert client.get("/x", {"a": 1}) == {"results": [1]}
    assert client.get("/x", {"a": 1}) == {"results": [1]}
    assert len(session.urls) == 1
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_get_retries_rate_limit_then_succeeds(tmp_path):
    session = FakeSession([FakeResponse(429, headers={"Retry-After": "0"}), FakeResponse(200, {"ok": True})])
    client = MassiveClient("k", cache_dir=tmp_path, session=session, sleep=lambda s: None)
    assert client.get("/y") == {"ok": True}
    assert len(session.urls) == 2


def test_get_raises_on_client_error_and_caches_nothing(tmp_path):
    session = FakeSession([FakeResponse(403)])
    client = MassiveClient("k", cache_dir=tmp_path, session=session, sleep=lambda s: None)
    with pytest.raises(RuntimeError, match="403"):
        client.get("/z")
    assert not list(tmp_path.glob("*.json"))


def test_get_all_follows_next_url(tmp_path):
    session = FakeSession([
        FakeResponse(200, {"results": [1, 2], "next_url": "https://api.massive.com/p2"}),
        FakeResponse(200, {"results": [3]}),
    ])
    client = MassiveClient("k", cache_dir=tmp_path, session=session, sleep=lambda s: None)
    assert client.get_all("/p1") == [1, 2, 3]
    assert session.urls[1] == "https://api.massive.com/p2"


def test_bearer_header_is_set(tmp_path):
    session = FakeSession([])
    MassiveClient("secret", cache_dir=tmp_path, session=session)
    assert session.headers["Authorization"] == "Bearer secret"


def test_retry_after_is_capped_at_sixty_seconds(tmp_path):
    session = FakeSession([FakeResponse(429, headers={"Retry-After": "3600"}), FakeResponse(200, {"ok": True})])
    slept = []
    client = MassiveClient("k", cache_dir=tmp_path, session=session, sleep=slept.append)
    assert client.get("/z") == {"ok": True}
    assert slept == [60.0]
    assert not list(tmp_path.glob("*.tmp"))


def test_concurrent_writes_same_url_never_corrupt_cache(tmp_path):
    import threading

    class SlowSession:
        def __init__(self):
            self.headers = {}
        def get(self, url, timeout):
            return FakeResponse(200, {"results": list(range(1000))})

    client = MassiveClient("k", cache_dir=tmp_path, session=SlowSession(), sleep=lambda s: None)
    threads = [threading.Thread(target=client.get, args=("/same",)) for _ in range(16)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    files = list(tmp_path.glob("*"))
    assert len(files) == 1 and files[0].suffix == ".json"
    assert json.loads(files[0].read_text()) == {"results": list(range(1000))}


class _FlakySession(FakeSession):

    def __init__(self, responses, exc, fail_times):
        super().__init__(responses)
        self.exc, self.fail_times = exc, fail_times

    def get(self, url, timeout):
        if len(self.urls) < self.fail_times:
            self.urls.append(url)
            raise self.exc("boom")
        return super().get(url, timeout)


@pytest.mark.parametrize("exc", [requests.exceptions.ConnectionError, requests.exceptions.Timeout])
def test_network_error_is_retried_once_then_succeeds(tmp_path, exc):
    session = _FlakySession([FakeResponse(200, {"results": [2]})], exc, 1)
    sleeps = []
    client = MassiveClient("k", cache_dir=tmp_path, session=session, sleep=sleeps.append)
    assert client.get("/x") == {"results": [2]}
    assert len(session.urls) == 2 and sleeps == [1]


def test_network_error_always_raises_after_max_attempts(tmp_path):
    session = _FlakySession([], requests.exceptions.ConnectionError, 99)
    client = MassiveClient("k", cache_dir=tmp_path, session=session, sleep=lambda s: None, max_attempts=3)
    with pytest.raises(requests.exceptions.ConnectionError):
        client.get("/x")
    assert len(session.urls) == 3
