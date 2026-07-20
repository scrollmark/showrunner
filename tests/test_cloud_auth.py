"""PKCE loopback login flow against a fully mocked authorization server."""

import base64
import hashlib
import urllib.request
from urllib.parse import parse_qs, urlparse

import pytest

httpx = pytest.importorskip("httpx", reason="cloud extra (httpx) not installed")

from showrunner.cloud import auth  # noqa: E402
from showrunner.cloud.credentials import Credentials, NotLoggedInError  # noqa: E402

SERVER = "https://api.example.test"


# ── PKCE + URL construction ──────────────────────────────────────────


def test_generate_pkce_s256_relationship():
    verifier, challenge = auth.generate_pkce()
    assert 43 <= len(verifier) <= 128
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert challenge == expected
    assert "=" not in challenge


def test_generate_pkce_unique():
    assert auth.generate_pkce() != auth.generate_pkce()


def test_build_authorize_url_contract():
    url = auth.build_authorize_url(
        SERVER + "/",
        redirect_uri="http://127.0.0.1:12345/callback",
        state="st",
        code_challenge="ch",
    )
    parsed = urlparse(url)
    assert url.startswith(SERVER + "/oauth/authorize?")
    qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert qs == {
        "response_type": "code",
        "client_id": "showrunner-cli",
        "redirect_uri": "http://127.0.0.1:12345/callback",
        "scope": "analysis:read analysis:upload offline_access",
        "state": "st",
        "code_challenge": "ch",
        "code_challenge_method": "S256",
        "resource": SERVER + "/api/v1",
    }


def test_default_resource_derived_from_server_url():
    assert auth.default_resource(SERVER + "/") == SERVER + "/api/v1"


# ── mocked AS ────────────────────────────────────────────────────────


class FakeAS:
    """Mocked token endpoint recording requests; MockTransport handler."""

    def __init__(self):
        self.requests: list[dict] = []
        self.access_tokens = iter(f"at-{i}" for i in range(1, 100))
        self.refresh_tokens = iter(f"rt-{i}" for i in range(1, 100))
        self.fail_with: dict | None = None  # {"status": int, "error": str}

    def transport(self):
        return httpx.MockTransport(self.handler)

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/oauth/token"
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.requests.append(form)
        if self.fail_with:
            return httpx.Response(
                self.fail_with.get("status", 400),
                json={"error": self.fail_with["error"]},
            )
        return httpx.Response(200, json={
            "access_token": next(self.access_tokens),
            "refresh_token": next(self.refresh_tokens),
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": "analysis:read analysis:upload offline_access",
        })


@pytest.fixture
def fake_as():
    return FakeAS()


# ── exchange / refresh / revoke ──────────────────────────────────────


def test_exchange_code_sends_pkce_no_secret(fake_as):
    creds = auth.exchange_code(
        SERVER,
        code="the-code",
        redirect_uri="http://127.0.0.1:1/callback",
        code_verifier="ver",
        transport=fake_as.transport(),
    )
    (req,) = fake_as.requests
    assert req["grant_type"] == "authorization_code"
    assert req["code"] == "the-code"
    assert req["client_id"] == "showrunner-cli"
    assert req["code_verifier"] == "ver"
    assert req["resource"] == SERVER + "/api/v1"
    assert "client_secret" not in req  # public client — never a secret
    assert creds.access_token == "at-1"
    assert creds.refresh_token == "rt-1"
    assert creds.expires_at is not None and not creds.expired


def test_refresh_rotates_tokens(fake_as):
    creds = Credentials(server_url=SERVER, access_token="old", refresh_token="rt-old")
    fresh = auth.refresh(creds, transport=fake_as.transport())
    (req,) = fake_as.requests
    assert req["grant_type"] == "refresh_token"
    assert req["refresh_token"] == "rt-old"
    assert fresh.access_token == "at-1"
    assert fresh.refresh_token == "rt-1"  # rotated
    assert fresh.refresh_token != creds.refresh_token


def test_refresh_expired_token_tells_user_to_login(fake_as):
    fake_as.fail_with = {"status": 400, "error": "invalid_grant"}
    creds = Credentials(server_url=SERVER, access_token="old", refresh_token="rt-dead")
    with pytest.raises(NotLoggedInError, match="showrunner login"):
        auth.refresh(creds, transport=fake_as.transport())


def test_refresh_without_refresh_token_raises():
    creds = Credentials(server_url=SERVER, access_token="only")
    with pytest.raises(NotLoggedInError, match="showrunner login"):
        auth.refresh(creds)


def test_revoke_best_effort():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["form"] = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        return httpx.Response(200)

    creds = Credentials(server_url=SERVER, access_token="at", refresh_token="rt")
    assert auth.revoke(creds, transport=httpx.MockTransport(handler)) is True
    assert seen["path"] == "/oauth/revoke"
    assert seen["form"]["token"] == "rt"


def test_revoke_tolerates_missing_endpoint():
    creds = Credentials(server_url=SERVER, access_token="at", refresh_token="rt")
    transport = httpx.MockTransport(lambda r: httpx.Response(404))
    assert auth.revoke(creds, transport=transport) is False


# ── full loopback flow ───────────────────────────────────────────────


def _browser_callback(extra_params: str = ""):
    """Fake `open_browser` that behaves like a user approving consent:
    parses redirect_uri+state out of the authorize URL and hits the
    loopback server the way the AS's 302 would."""

    def opener(url: str) -> bool:
        qs = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        target = f"{qs['redirect_uri']}?code=auth-code-1&state={qs['state']}{extra_params}"
        with urllib.request.urlopen(target) as resp:
            assert resp.status == 200
        return True

    return opener


def test_login_full_loopback_flow(fake_as):
    messages = []
    creds = auth.login(
        SERVER,
        open_browser=_browser_callback(),
        echo=messages.append,
        transport=fake_as.transport(),
        timeout=10,
    )
    assert creds.access_token == "at-1"
    assert creds.refresh_token == "rt-1"
    (req,) = fake_as.requests
    assert req["code"] == "auth-code-1"
    # redirect_uri is the ephemeral loopback the server actually used
    assert req["redirect_uri"].startswith("http://127.0.0.1:")
    assert req["redirect_uri"].endswith("/callback")
    # code_verifier matches the challenge sent in the authorize URL
    url_line = next(m for m in messages if "oauth/authorize" in m)
    url_qs = {k: v[0] for k, v in parse_qs(urlparse(url_line.strip()).query).items()}
    expected_challenge = (
        base64.urlsafe_b64encode(
            hashlib.sha256(req["code_verifier"].encode()).digest()
        ).rstrip(b"=").decode()
    )
    assert url_qs["code_challenge"] == expected_challenge


def test_login_state_mismatch_aborts(fake_as):
    def evil_opener(url: str) -> bool:
        qs = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        with urllib.request.urlopen(
            f"{qs['redirect_uri']}?code=auth-code-1&state=WRONG"
        ) as resp:
            assert resp.status == 200
        return True

    with pytest.raises(auth.LoginError, match="[Ss]tate"):
        auth.login(
            SERVER, open_browser=evil_opener, echo=lambda m: None,
            transport=fake_as.transport(), timeout=10,
        )
    assert fake_as.requests == []  # never exchanged the code


def test_login_denied_consent(fake_as):
    def denying_opener(url: str) -> bool:
        qs = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        with urllib.request.urlopen(
            f"{qs['redirect_uri']}?error=access_denied&state={qs['state']}"
        ) as resp:
            assert resp.status == 200
        return True

    with pytest.raises(auth.LoginError, match="access_denied"):
        auth.login(
            SERVER, open_browser=denying_opener, echo=lambda m: None,
            transport=fake_as.transport(), timeout=10,
        )


def test_login_timeout_suggests_no_browser(fake_as):
    with pytest.raises(auth.LoginError, match="no-browser"):
        auth.login(
            SERVER, open_browser=lambda url: True, echo=lambda m: None,
            transport=fake_as.transport(), timeout=0.2,
        )


def test_login_token_error_surfaces(fake_as):
    fake_as.fail_with = {"status": 400, "error": "invalid_request"}
    with pytest.raises(auth.LoginError, match="invalid_request"):
        auth.login(
            SERVER, open_browser=_browser_callback(), echo=lambda m: None,
            transport=fake_as.transport(), timeout=10,
        )


# ── --no-browser paste flow ──────────────────────────────────────────


def test_login_no_browser_paste_full_url(fake_as):
    messages = []
    state_holder = {}

    def prompt(text: str) -> str:
        url_line = next(m for m in messages if "oauth/authorize" in m)
        qs = {k: v[0] for k, v in parse_qs(urlparse(url_line.strip()).query).items()}
        state_holder["state"] = qs["state"]
        return f"{qs['redirect_uri']}?code=pasted-code&state={qs['state']}"

    creds = auth.login(
        SERVER, no_browser=True, echo=messages.append, prompt=prompt,
        transport=fake_as.transport(),
    )
    assert creds.access_token == "at-1"
    (req,) = fake_as.requests
    assert req["code"] == "pasted-code"
    assert req["redirect_uri"] == "http://127.0.0.1:8765/callback"


def test_login_no_browser_paste_bare_code(fake_as):
    creds = auth.login(
        SERVER, no_browser=True, echo=lambda m: None,
        prompt=lambda text: "  bare-code  ",
        transport=fake_as.transport(),
    )
    assert creds.access_token == "at-1"
    assert fake_as.requests[0]["code"] == "bare-code"


def test_login_no_browser_pasted_state_mismatch(fake_as):
    with pytest.raises(auth.LoginError, match="[Ss]tate"):
        auth.login(
            SERVER, no_browser=True, echo=lambda m: None,
            prompt=lambda text: "http://127.0.0.1:8765/callback?code=x&state=WRONG",
            transport=fake_as.transport(),
        )


def test_login_no_browser_pasted_error(fake_as):
    with pytest.raises(auth.LoginError, match="access_denied"):
        auth.login(
            SERVER, no_browser=True, echo=lambda m: None,
            prompt=lambda text: "http://127.0.0.1:8765/callback?error=access_denied",
            transport=fake_as.transport(),
        )
