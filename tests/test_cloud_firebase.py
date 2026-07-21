"""Firebase login mode: sign-in, refresh rotation, client dispatch,
local whoami decode, and analyze-with-firebase end to end.

Both Google endpoints (identitytoolkit sign-in, securetoken refresh) are
served by httpx.MockTransport handlers routing on the request host — no
real network anywhere.
"""

import base64
import json
import time
from unittest.mock import patch

import pytest
from click.testing import CliRunner

httpx = pytest.importorskip("httpx", reason="cloud extra (httpx) not installed")

from showrunner.cloud import (  # noqa: E402
    firebase,
    resolve_auth_method,
    resolve_firebase_api_key,
)
from showrunner.cloud.client import CloudClient  # noqa: E402
from showrunner.cloud.credentials import (  # noqa: E402
    Credentials,
    CredentialStore,
    NotLoggedInError,
)

SERVER = "https://api.example.test"
API_KEY = "AIzaTestKey123"
EMAIL = "john@scrollmark.com"
PASSWORD = "hunter2"
USER_ID = "firebase-uid-1"


def _jwt(claims: dict) -> str:
    """Build an unsigned JWT-shaped token (header.payload.signature)."""

    def b64(d: dict) -> str:
        return (
            base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
        )

    return f"{b64({'alg': 'RS256', 'typ': 'JWT'})}.{b64(claims)}.fakesig"


def _id_token(n: int = 1) -> str:
    return _jwt({
        "user_id": USER_ID,
        "sub": USER_ID,
        "email": EMAIL,
        "exp": int(time.time()) + 3600,
        "iat": n,  # varies per refresh so rotated tokens differ
    })


class FakeGoogle:
    """MockTransport handler for both Google auth hosts (+ optional API)."""

    def __init__(self):
        self.sign_in_requests: list[httpx.Request] = []
        self.refresh_requests: list[dict] = []
        self.sign_in_error: str | None = None  # Identity Toolkit error code
        self.refresh_error: str | None = None  # securetoken error code
        self.valid_tokens: set[str] = set()
        self.api_requests: list[httpx.Request] = []
        self._counter = 0

    def transport(self):
        return httpx.MockTransport(self.handler)

    def handler(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "identitytoolkit.googleapis.com":
            assert request.url.path == "/v1/accounts:signInWithPassword"
            assert request.url.params["key"] == API_KEY
            self.sign_in_requests.append(request)
            if self.sign_in_error:
                return httpx.Response(
                    400, json={"error": {"code": 400, "message": self.sign_in_error}}
                )
            body = json.loads(request.content)
            assert body["returnSecureToken"] is True
            token = _id_token(0)
            self.valid_tokens.add(token)
            return httpx.Response(200, json={
                "idToken": token,
                "refreshToken": "fb-rt-0",
                "expiresIn": "3600",
                "localId": USER_ID,
                "email": body["email"],
            })
        if host == "securetoken.googleapis.com":
            assert request.url.path == "/v1/token"
            assert request.url.params["key"] == API_KEY
            form = dict(
                pair.split("=", 1) for pair in request.content.decode().split("&")
            )
            self.refresh_requests.append(form)
            if self.refresh_error:
                return httpx.Response(
                    400, json={"error": {"code": 400, "message": self.refresh_error}}
                )
            self._counter += 1
            token = _id_token(self._counter)
            self.valid_tokens.add(token)
            return httpx.Response(200, json={
                "id_token": token,
                "refresh_token": f"fb-rt-{self._counter}",
                "expires_in": "3600",
            })
        return self.api_handler(request)

    def api_handler(self, request: httpx.Request) -> httpx.Response:
        self.api_requests.append(request)
        authz = request.headers.get("Authorization", "")
        if authz.removeprefix("Bearer ") not in self.valid_tokens:
            return httpx.Response(401, json={"detail": "unauthorized"})
        return httpx.Response(200, json={"ok": True})


def _firebase_creds(**kw) -> Credentials:
    defaults = dict(
        server_url=SERVER, access_token=_id_token(), refresh_token="fb-rt-0",
        expires_at=time.time() + 3600, method="firebase",
        firebase_api_key=API_KEY,
    )
    defaults.update(kw)
    return Credentials(**defaults)


def _store(tmp_path, creds=None) -> CredentialStore:
    store = CredentialStore(path=tmp_path / "credentials.json", use_keyring=False)
    if creds is not None:
        store.save(creds)
    return store


# ── sign in ──────────────────────────────────────────────────────────


def test_sign_in_success_builds_firebase_credentials():
    google = FakeGoogle()
    creds = firebase.sign_in(
        SERVER, EMAIL, PASSWORD, api_key=API_KEY, transport=google.transport()
    )
    assert creds.method == "firebase"
    assert creds.server_url == SERVER
    assert creds.refresh_token == "fb-rt-0"
    assert creds.firebase_api_key == API_KEY
    assert creds.expires_at == pytest.approx(time.time() + 3600, abs=10)
    assert firebase.decode_id_token(creds.access_token)["email"] == EMAIL
    (req,) = google.sign_in_requests
    body = json.loads(req.content)
    assert body == {"email": EMAIL, "password": PASSWORD, "returnSecureToken": True}


@pytest.mark.parametrize("code,expected", [
    ("EMAIL_NOT_FOUND", "No account exists"),
    ("INVALID_PASSWORD", "Google sign-in"),
    ("INVALID_LOGIN_CREDENTIALS", "Google sign-in"),
    ("USER_DISABLED", "disabled"),
    ("TOO_MANY_ATTEMPTS_TRY_LATER : Try again later.", "Too many failed"),
])
def test_sign_in_errors_are_friendly(code, expected):
    google = FakeGoogle()
    google.sign_in_error = code
    with pytest.raises(firebase.FirebaseLoginError, match=expected):
        firebase.sign_in(
            SERVER, EMAIL, "wrong", api_key=API_KEY, transport=google.transport()
        )


def test_sign_in_without_api_key_is_actionable():
    with pytest.raises(firebase.FirebaseLoginError, match="firebase_api_key"):
        firebase.sign_in(SERVER, EMAIL, PASSWORD, api_key="")


# ── refresh ──────────────────────────────────────────────────────────


def test_refresh_rotates_tokens():
    google = FakeGoogle()
    creds = firebase.refresh(_firebase_creds(), transport=google.transport())
    assert creds.method == "firebase"
    assert creds.refresh_token == "fb-rt-1"
    assert creds.firebase_api_key == API_KEY
    assert firebase.decode_id_token(creds.access_token)["iat"] == 1
    (form,) = google.refresh_requests
    assert form["grant_type"] == "refresh_token"
    assert form["refresh_token"] == "fb-rt-0"


def test_refresh_expired_token_says_login_again():
    google = FakeGoogle()
    google.refresh_error = "TOKEN_EXPIRED"
    with pytest.raises(NotLoggedInError, match="showrunner login"):
        firebase.refresh(_firebase_creds(), transport=google.transport())


def test_refresh_without_refresh_token_says_login_again():
    with pytest.raises(NotLoggedInError, match="showrunner login"):
        firebase.refresh(_firebase_creds(refresh_token=None))


# ── local ID token decode ────────────────────────────────────────────


def test_decode_id_token_claims():
    claims = firebase.decode_id_token(_id_token())
    assert claims["user_id"] == USER_ID
    assert claims["email"] == EMAIL


def test_decode_id_token_garbage_raises():
    with pytest.raises(firebase.FirebaseLoginError):
        firebase.decode_id_token("not-a-jwt")


# ── credentials: method tag round-trip ───────────────────────────────


def test_credentials_roundtrip_keeps_method_and_api_key(tmp_path):
    store = _store(tmp_path, _firebase_creds())
    loaded = store.load(SERVER)
    assert loaded.method == "firebase"
    assert loaded.firebase_api_key == API_KEY


def test_credentials_without_method_default_to_oauth():
    d = _firebase_creds().to_dict()
    del d["method"]
    del d["firebase_api_key"]
    loaded = Credentials.from_dict(d)
    assert loaded.method == "oauth"
    assert loaded.firebase_api_key is None


def test_firebase_expiry_skew_is_five_minutes():
    # 2 min to expiry: expired for firebase (300s skew), fresh for oauth (60s)
    soon = time.time() + 120
    assert _firebase_creds(expires_at=soon).expired
    assert not Credentials(
        server_url=SERVER, access_token="at", expires_at=soon
    ).expired


# ── config resolution ────────────────────────────────────────────────


def test_auth_method_defaults_to_oauth():
    # OAuth is the default (ready for the backend chain deploy —
    # scrollmark/showrunner#55); firebase via override/--with-password.
    assert resolve_auth_method(None) == "oauth"
    assert resolve_auth_method(None, override="firebase") == "firebase"
    with pytest.raises(ValueError, match="auth_method"):
        resolve_auth_method(None, override="saml")


def test_firebase_api_key_config_override():
    from showrunner.config import Config

    assert resolve_firebase_api_key(None) == firebase.DEFAULT_FIREBASE_API_KEY
    config = Config.from_dict({"cloud": {"firebase_api_key": "AIzaOther"}})
    assert resolve_firebase_api_key(config) == "AIzaOther"


# ── client dispatch ──────────────────────────────────────────────────


def test_client_401_refreshes_via_securetoken(tmp_path):
    google = FakeGoogle()  # stored token not in valid_tokens → 401 first
    store = _store(tmp_path, _firebase_creds(access_token=_jwt({"stale": True})))
    with CloudClient(SERVER, store=store, transport=google.transport()) as api:
        resp = api.get("/api/v1/drafts/x/analysis")
    assert resp.status_code == 200
    assert len(google.api_requests) == 2  # 401 then retry
    assert len(google.refresh_requests) == 1  # refreshed via Google, not /oauth
    # rotation persisted with the method tag intact
    saved = store.load(SERVER)
    assert saved.method == "firebase"
    assert saved.refresh_token == "fb-rt-1"


def test_client_proactive_refresh_within_five_minutes(tmp_path):
    google = FakeGoogle()
    store = _store(
        tmp_path,
        _firebase_creds(
            access_token=_jwt({"stale": True}), expires_at=time.time() + 120
        ),
    )
    with CloudClient(SERVER, store=store, transport=google.transport()) as api:
        resp = api.get("/api/v1/me")
    assert resp.status_code == 200
    # refreshed BEFORE hitting the API — no 401 round trip
    assert len(google.api_requests) == 1
    assert len(google.refresh_requests) == 1


# ── analyze with firebase credentials, end to end ────────────────────


def test_analyze_end_to_end_with_firebase_credentials(tmp_path):
    from showrunner.cloud import analyze

    analysis = {"executive_summary": "Tight explainer.", "hooks": []}
    post_id = "d-1"
    google = FakeGoogle()
    polls = {"n": 0}

    def drafts_api(request: httpx.Request) -> httpx.Response:
        google.api_requests.append(request)
        authz = request.headers.get("Authorization", "")
        if authz.removeprefix("Bearer ") not in google.valid_tokens:
            return httpx.Response(401, json={"detail": "unauthorized"})
        if request.url.path == "/api/v1/drafts/upload":
            request.read()
            return httpx.Response(201, json={"post_id": post_id, "user_id": "u1"})
        if request.url.path == f"/api/v1/drafts/{post_id}/analysis":
            polls["n"] += 1
            if polls["n"] == 1:
                return httpx.Response(404, json={"detail": "not yet"})
            return httpx.Response(200, json={"post_id": post_id, "analysis": analysis})
        raise AssertionError(f"unexpected: {request.url.path}")

    google.api_handler = drafts_api
    # Stored credential is a stale firebase session: forces the 401 →
    # securetoken refresh → retry path inside the analyze flow.
    store = _store(tmp_path, _firebase_creds(access_token=_jwt({"stale": True})))
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 100)

    with CloudClient(SERVER, store=store, transport=google.transport()) as client:
        result = analyze.upload_and_analyze(client, video, sleep=lambda s: None)

    assert result == analysis
    assert len(google.refresh_requests) == 1  # firebase refresh, no /oauth/token
    assert store.load(SERVER).method == "firebase"


# ── CLI ──────────────────────────────────────────────────────────────


@pytest.fixture
def cred_file(tmp_path, monkeypatch):
    path = tmp_path / "credentials.json"
    monkeypatch.setattr(
        "showrunner.cloud.credentials.default_credentials_path", lambda: path
    )
    monkeypatch.setattr(CredentialStore, "_keyring", lambda self: None)
    monkeypatch.delenv("SHOWRUNNER_TOKEN", raising=False)
    return path


DEFAULT_SERVER = "https://api.gpt.social"


def test_cli_login_with_password_prompts_and_saves(cred_file):
    from showrunner.cli.main import cli

    creds = _firebase_creds(server_url=DEFAULT_SERVER)
    with patch("showrunner.cloud.firebase.sign_in", return_value=creds) as mock:
        result = CliRunner().invoke(
            cli, ["login", "--with-password"],
            input=f"{EMAIL}\n{PASSWORD}\n", catch_exceptions=False,
        )
    assert result.exit_code == 0
    assert mock.call_args.args == (DEFAULT_SERVER, EMAIL, PASSWORD)
    assert mock.call_args.kwargs["api_key"] == firebase.DEFAULT_FIREBASE_API_KEY
    assert PASSWORD not in result.output  # hide_input: never echoed
    assert "Method: firebase" in result.output
    saved = json.loads(cred_file.read_text())[DEFAULT_SERVER]
    assert saved["method"] == "firebase"


def test_cli_login_firebase_bad_password_message(cred_file):
    from showrunner.cli.main import cli

    with patch(
        "showrunner.cloud.firebase.sign_in",
        side_effect=firebase.FirebaseLoginError("Email or password is incorrect."),
    ):
        result = CliRunner().invoke(
            cli, ["login", "--with-password"], input=f"{EMAIL}\nnope\n"
        )
    assert result.exit_code != 0
    assert "Email or password is incorrect" in result.output


def test_cli_whoami_firebase_decodes_locally(cred_file):
    from showrunner.cli.main import cli

    CredentialStore().save(_firebase_creds(server_url=DEFAULT_SERVER))
    # No transport injection and no CloudClient patch: this only passes
    # because the firebase path never talks to the server.
    result = CliRunner().invoke(cli, ["whoami"], catch_exceptions=False)
    assert result.exit_code == 0
    assert EMAIL in result.output
    assert USER_ID in result.output
    assert "decoded locally" in result.output


def test_cli_whoami_firebase_json(cred_file):
    from showrunner.cli.main import cli

    CredentialStore().save(_firebase_creds(server_url=DEFAULT_SERVER))
    result = CliRunner().invoke(cli, ["whoami", "--json"], catch_exceptions=False)
    doc = json.loads(result.output)
    assert doc["logged_in"] is True
    assert doc["method"] == "firebase"
    assert doc["email"] == EMAIL
    assert doc["user_id"] == USER_ID
    assert doc["identity_source"] == "local_token"


def test_cli_logout_firebase_skips_oauth_revocation(cred_file):
    from showrunner.cli.main import cli

    CredentialStore().save(_firebase_creds(server_url=DEFAULT_SERVER))
    with patch("showrunner.cloud.auth.revoke") as mock_revoke:
        result = CliRunner().invoke(cli, ["logout"], catch_exceptions=False)
    assert result.exit_code == 0
    assert not mock_revoke.called
    assert "local credentials cleared" in result.output
    assert CredentialStore().load(DEFAULT_SERVER) is None
