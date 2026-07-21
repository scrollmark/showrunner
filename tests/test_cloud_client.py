"""CloudClient: Bearer + X-Client-Surface headers, 401 refresh-retry."""

import time
from urllib.parse import parse_qs

import pytest

httpx = pytest.importorskip("httpx", reason="cloud extra (httpx) not installed")

from showrunner.cloud.client import CloudClient  # noqa: E402
from showrunner.cloud.credentials import (  # noqa: E402
    Credentials,
    CredentialStore,
    NotLoggedInError,
)

SERVER = "https://api.example.test"


class FakeServer:
    """One MockTransport serving both /oauth/token and the API."""

    def __init__(self, valid_tokens=("at-1",)):
        self.valid_tokens = set(valid_tokens)
        self.api_requests: list[httpx.Request] = []
        self.token_requests: list[dict] = []
        self.refresh_fails = False
        self._counter = 0

    def transport(self):
        return httpx.MockTransport(self.handler)

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_requests.append(form)
            if self.refresh_fails:
                return httpx.Response(400, json={"error": "invalid_grant"})
            self._counter += 1
            token = f"at-fresh-{self._counter}"
            self.valid_tokens.add(token)
            return httpx.Response(200, json={
                "access_token": token,
                "refresh_token": f"rt-fresh-{self._counter}",
                "expires_in": 3600,
            })
        self.api_requests.append(request)
        authz = request.headers.get("Authorization", "")
        if authz.removeprefix("Bearer ") not in self.valid_tokens:
            return httpx.Response(401, json={"detail": "unauthorized"})
        return httpx.Response(200, json={"ok": True, "path": request.url.path})


def _store(tmp_path, creds=None) -> CredentialStore:
    store = CredentialStore(path=tmp_path / "credentials.json", use_keyring=False)
    if creds is not None:
        store.save(creds)
    return store


def _creds(**kw) -> Credentials:
    defaults = dict(
        server_url=SERVER, access_token="at-1", refresh_token="rt-1",
        expires_at=time.time() + 3600,
    )
    defaults.update(kw)
    return Credentials(**defaults)


def test_injects_bearer_and_surface_headers(tmp_path):
    srv = FakeServer()
    with CloudClient(SERVER, store=_store(tmp_path, _creds()),
                     transport=srv.transport()) as api:
        resp = api.get("/api/v1/me")
    assert resp.status_code == 200
    (req,) = srv.api_requests
    assert req.headers["Authorization"] == "Bearer at-1"
    assert req.headers["X-Client-Surface"] == "cli"


def test_not_logged_in_raises(tmp_path):
    with CloudClient(SERVER, store=_store(tmp_path),
                     transport=FakeServer().transport()) as api:
        with pytest.raises(NotLoggedInError, match="showrunner login"):
            api.get("/api/v1/me")


def test_401_triggers_one_refresh_and_retry(tmp_path):
    srv = FakeServer(valid_tokens=())  # stored token is invalid
    store = _store(tmp_path, _creds(access_token="at-stale"))
    with CloudClient(SERVER, store=store, transport=srv.transport()) as api:
        resp = api.get("/api/v1/me")
    assert resp.status_code == 200
    assert len(srv.api_requests) == 2  # 401 then retry
    assert srv.api_requests[1].headers["Authorization"] == "Bearer at-fresh-1"
    (tok_req,) = srv.token_requests
    assert tok_req["grant_type"] == "refresh_token"
    # rotation persisted
    saved = store.load(SERVER)
    assert saved.access_token == "at-fresh-1"
    assert saved.refresh_token == "rt-fresh-1"


def test_persistent_401_after_refresh_returns_response(tmp_path):
    """One retry only: if the refreshed token still 401s, surface it."""
    srv = FakeServer(valid_tokens=())

    original = srv.handler

    def never_valid(request):
        resp = original(request)
        if request.url.path != "/oauth/token" and resp.status_code == 200:
            return httpx.Response(401, json={"detail": "still no"})
        return resp

    store = _store(tmp_path, _creds(access_token="at-stale"))
    with CloudClient(SERVER, store=store,
                     transport=httpx.MockTransport(never_valid)) as api:
        resp = api.get("/api/v1/me")
    assert resp.status_code == 401
    assert len(srv.token_requests) == 1  # exactly one refresh attempt


def test_proactive_refresh_when_expired(tmp_path):
    srv = FakeServer(valid_tokens=())
    store = _store(tmp_path, _creds(access_token="at-old",
                                    expires_at=time.time() - 5))
    with CloudClient(SERVER, store=store, transport=srv.transport()) as api:
        resp = api.get("/api/v1/uploads")
    assert resp.status_code == 200
    # refreshed BEFORE hitting the API — no 401 round trip
    assert len(srv.api_requests) == 1
    assert srv.api_requests[0].headers["Authorization"] == "Bearer at-fresh-1"


def test_expired_refresh_token_raises_login_message(tmp_path):
    srv = FakeServer(valid_tokens=())
    srv.refresh_fails = True
    store = _store(tmp_path, _creds(access_token="at-stale"))
    with CloudClient(SERVER, store=store, transport=srv.transport()) as api:
        with pytest.raises(NotLoggedInError, match="showrunner login"):
            api.get("/api/v1/me")


def test_env_token_used_and_not_refreshed(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOWRUNNER_TOKEN", "ci-token")
    srv = FakeServer(valid_tokens=("ci-token",))
    with CloudClient(SERVER, store=_store(tmp_path),
                     transport=srv.transport()) as api:
        resp = api.get("/api/v1/me")
    assert resp.status_code == 200
    assert srv.api_requests[0].headers["Authorization"] == "Bearer ci-token"
    assert srv.token_requests == []


def test_env_token_401_raises_actionable_error(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOWRUNNER_TOKEN", "bad-ci-token")
    srv = FakeServer(valid_tokens=())
    with CloudClient(SERVER, store=_store(tmp_path),
                     transport=srv.transport()) as api:
        with pytest.raises(NotLoggedInError, match="SHOWRUNNER_TOKEN"):
            api.get("/api/v1/me")
    assert srv.token_requests == []  # never tries to refresh an env token
