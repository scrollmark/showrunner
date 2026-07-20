"""OAuth 2.1 PKCE loopback login flow (RFC 8252 native-app flow).

Shared contract with the server (do not change unilaterally):

- Authorize ``GET {server}/oauth/authorize``, token ``POST {server}/oauth/token``
- ``client_id="showrunner-cli"`` — public client, NO secret, PKCE S256 required
- Redirect: ``http://127.0.0.1:{ephemeral-port}/callback`` (any port)
- Scopes: ``analysis:read analysis:upload offline_access``
- ``resource`` param: the server's public-API resource URL (default
  derived from server_url: ``{server_url}/api/v1``)
- Access tokens ~1h; refresh tokens rotate on use

httpx is imported lazily (optional `[cloud]` dep group).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlparse

from showrunner.cloud.credentials import CloudError, Credentials, NotLoggedInError

CLIENT_ID = "showrunner-cli"
SCOPES = "analysis:read analysis:upload offline_access"

#: Redirect port used in --no-browser mode where no loopback server
#: listens (the user pastes the redirect URL back). Any port is
#: contract-valid for the showrunner-cli client.
NO_BROWSER_PORT = 8765

#: How long `login()` waits for the browser callback before giving up.
DEFAULT_CALLBACK_TIMEOUT = 300.0


class LoginError(CloudError):
    """The login flow failed (denied consent, bad state, token error...)."""


# ── PKCE ─────────────────────────────────────────────────────────────


def generate_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) per RFC 7636 S256."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def default_resource(server_url: str) -> str:
    """Public-API resource URL derived from the server URL."""
    return server_url.rstrip("/") + "/api/v1"


def build_authorize_url(
    server_url: str,
    *,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    resource: str | None = None,
    scopes: str = SCOPES,
) -> str:
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "resource": resource or default_resource(server_url),
    }
    return f"{server_url.rstrip('/')}/oauth/authorize?{urlencode(params)}"


# ── token endpoint ───────────────────────────────────────────────────


def _token_request(server_url: str, data: dict, transport=None) -> dict:
    """POST the token endpoint; return the parsed JSON or raise LoginError."""
    import httpx  # noqa: PLC0415 — optional dep, lazy import

    url = server_url.rstrip("/") + "/oauth/token"
    with httpx.Client(transport=transport, timeout=30.0) as client:
        resp = client.post(url, data=data)
    if resp.status_code != 200:
        try:
            body = resp.json()
        except Exception:
            body = {}
        error = body.get("error", f"http_{resp.status_code}")
        description = body.get("error_description", "")
        raise LoginError(
            f"Token request failed: {error}"
            + (f" — {description}" if description else "")
        )
    return resp.json()


def _credentials_from_token_response(
    server_url: str, payload: dict, *, fallback_refresh: str | None = None
) -> Credentials:
    expires_in = payload.get("expires_in")
    return Credentials(
        server_url=server_url.rstrip("/"),
        access_token=payload["access_token"],
        # Rotation: the server issues a new refresh token on each use; if
        # it ever omits one, keep the old (some servers rotate lazily).
        refresh_token=payload.get("refresh_token") or fallback_refresh,
        expires_at=(time.time() + float(expires_in)) if expires_in else None,
        scopes=payload.get("scope"),
        token_type=payload.get("token_type", "Bearer"),
        source="login",
    )


def exchange_code(
    server_url: str,
    *,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    resource: str | None = None,
    transport=None,
) -> Credentials:
    """Exchange an authorization code for tokens."""
    payload = _token_request(
        server_url,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": CLIENT_ID,
            "code_verifier": code_verifier,
            "resource": resource or default_resource(server_url),
        },
        transport=transport,
    )
    return _credentials_from_token_response(server_url, payload)


def refresh(creds: Credentials, *, transport=None) -> Credentials:
    """Refresh an access token; refresh tokens rotate on use.

    Raises NotLoggedInError when the refresh token is gone or rejected
    (expired/revoked) — the user must `showrunner login` again.
    """
    if not creds.refresh_token:
        raise NotLoggedInError(
            "Session expired and no refresh token is available. "
            "Run `showrunner login` to authenticate again."
        )
    try:
        payload = _token_request(
            creds.server_url,
            {
                "grant_type": "refresh_token",
                "refresh_token": creds.refresh_token,
                "client_id": CLIENT_ID,
                "resource": default_resource(creds.server_url),
            },
            transport=transport,
        )
    except LoginError as e:
        raise NotLoggedInError(
            f"Your session has expired ({e}). Run `showrunner login` to "
            "authenticate again."
        ) from e
    return _credentials_from_token_response(
        creds.server_url, payload, fallback_refresh=creds.refresh_token
    )


def revoke(creds: Credentials, *, transport=None) -> bool:
    """Best-effort RFC 7009 revocation of the refresh token.

    Returns True when the server acknowledged, False otherwise (the
    server may not expose /oauth/revoke yet — logout still clears local
    storage either way).
    """
    token = creds.refresh_token or creds.access_token
    if not token:
        return False
    try:
        import httpx  # noqa: PLC0415

        url = creds.server_url.rstrip("/") + "/oauth/revoke"
        with httpx.Client(transport=transport, timeout=10.0) as client:
            resp = client.post(url, data={"token": token, "client_id": CLIENT_ID})
        return resp.status_code < 400
    except Exception:
        return False


# ── loopback callback server ─────────────────────────────────────────


class _CallbackHandler(BaseHTTPRequestHandler):
    """Catches GET /callback?code=...&state=... from the browser."""

    def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        self.server.callback_result = qs  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if "error" in qs:
            body = "<h1>Login failed</h1><p>You can close this tab and return to the terminal.</p>"
        else:
            body = "<h1>Logged in to Showrunner</h1><p>You can close this tab and return to the terminal.</p>"
        self.wfile.write(f"<html><body>{body}</body></html>".encode())
        self.server.callback_event.set()  # type: ignore[attr-defined]

    def log_message(self, *args):  # silence request logging
        return


class LoopbackServer:
    """Ephemeral localhost HTTP server for the OAuth redirect."""

    def __init__(self):
        self.httpd = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
        self.httpd.callback_result = None  # type: ignore[attr-defined]
        self.httpd.callback_event = threading.Event()  # type: ignore[attr-defined]
        self.port = self.httpd.server_address[1]
        self.redirect_uri = f"http://127.0.0.1:{self.port}/callback"
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    def wait(self, timeout: float) -> dict | None:
        """Block until the callback arrives; None on timeout."""
        if self.httpd.callback_event.wait(timeout):  # type: ignore[attr-defined]
            return self.httpd.callback_result  # type: ignore[attr-defined]
        return None

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)


# ── the flow ─────────────────────────────────────────────────────────


def _parse_pasted_redirect(pasted: str, expected_state: str) -> str:
    """Extract the authorization code from a pasted redirect URL or raw code."""
    pasted = pasted.strip()
    if "?" in pasted or pasted.startswith(("http://", "https://")):
        qs = {k: v[0] for k, v in parse_qs(urlparse(pasted).query).items()}
        if "error" in qs:
            raise LoginError(f"Authorization failed: {qs['error']}")
        code = qs.get("code")
        if not code:
            raise LoginError("No `code` parameter found in the pasted URL.")
        state = qs.get("state")
        if state is not None and state != expected_state:
            raise LoginError("State mismatch — possible CSRF; aborting login.")
        return code
    return pasted


def login(
    server_url: str,
    *,
    no_browser: bool = False,
    open_browser: Callable[[str], object] = webbrowser.open,
    echo: Callable[[str], None] = print,
    prompt: Callable[[str], str] = input,
    timeout: float = DEFAULT_CALLBACK_TIMEOUT,
    transport=None,
) -> Credentials:
    """Run the full PKCE loopback login flow; return fresh Credentials.

    `echo`/`prompt`/`open_browser` are injectable for the CLI (stderr in
    --json mode) and for tests. The returned credentials are NOT saved —
    the caller persists them via CredentialStore.
    """
    server_url = server_url.rstrip("/")
    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(24)

    if no_browser:
        redirect_uri = f"http://127.0.0.1:{NO_BROWSER_PORT}/callback"
        url = build_authorize_url(
            server_url, redirect_uri=redirect_uri, state=state, code_challenge=challenge
        )
        echo("Open this URL in a browser to authorize showrunner:")
        echo("")
        echo(f"  {url}")
        echo("")
        echo(
            "After approving, the browser will try to redirect to a localhost "
            "URL that won't load — copy that full URL (or just its `code` "
            "parameter) from the address bar and paste it below."
        )
        pasted = prompt("Paste the redirect URL (or code): ")
        code = _parse_pasted_redirect(pasted, state)
        return exchange_code(
            server_url,
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=verifier,
            transport=transport,
        )

    server = LoopbackServer()
    server.start()
    try:
        url = build_authorize_url(
            server_url,
            redirect_uri=server.redirect_uri,
            state=state,
            code_challenge=challenge,
        )
        echo("Opening your browser to log in to Showrunner Cloud...")
        echo("If the browser doesn't open, visit:")
        echo("")
        echo(f"  {url}")
        echo("")
        try:
            opened = open_browser(url)
        except Exception:
            opened = False
        if not opened:
            echo("(Could not open a browser automatically — use the URL above.)")
        result = server.wait(timeout)
    finally:
        server.stop()

    if result is None:
        raise LoginError(
            f"Timed out after {int(timeout)}s waiting for the browser callback. "
            "Re-run with --no-browser to paste the redirect URL manually."
        )
    if "error" in result:
        desc = result.get("error_description", "")
        raise LoginError(
            f"Authorization failed: {result['error']}"
            + (f" — {desc}" if desc else "")
        )
    if result.get("state") != state:
        raise LoginError("State mismatch — possible CSRF; aborting login.")
    code = result.get("code")
    if not code:
        raise LoginError("Callback did not include an authorization code.")
    return exchange_code(
        server_url,
        code=code,
        redirect_uri=server.redirect_uri,
        code_verifier=verifier,
        transport=transport,
    )
