"""Firebase email/password login via Google's public Identity Toolkit API.

Prototype path: TODAY's production SocialGPT drafts endpoints authenticate
Firebase ID tokens only (`get_current_user` verifies them directly); the
OAuth authorization server the PKCE flow in :mod:`showrunner.cloud.auth`
talks to is not deployed yet. This module signs in against Firebase Auth
the same way ``firebase-tools`` does — the public Identity Toolkit REST
API keyed by the project's web API key. Firebase web API keys are public
by design (they identify the project, not a secret; the production web
frontend ships the same key to every browser).

The default auth method is "firebase" for now so
``showrunner login && showrunner analyze`` works against production
today. scrollmark/showrunner#55 tracks flipping the default back to
"oauth" once the platform OAuth chain deploys.

Endpoints (Google-hosted; mocked with httpx.MockTransport in tests):

- Sign in: ``POST {identitytoolkit}/v1/accounts:signInWithPassword?key=K``
  with JSON ``{email, password, returnSecureToken: true}`` →
  ``{idToken, refreshToken, expiresIn, localId, email}``.
- Refresh: ``POST {securetoken}/v1/token?key=K`` with form
  ``grant_type=refresh_token&refresh_token=...`` →
  ``{id_token, refresh_token, expires_in}`` (refresh tokens may rotate;
  the returned one is persisted).

httpx is imported lazily (optional `[cloud]` dep group).
"""

from __future__ import annotations

import base64
import json
import time

from showrunner.cloud.credentials import CloudError, Credentials, NotLoggedInError

#: Web API key of the production SocialGPT Firebase project — the same
#: public key the deployed frontend (app.gpt.social) embeds in its
#: browser bundle. Override with ``cloud.firebase_api_key`` in
#: .showrunner.yaml (e.g. to point at staging).
DEFAULT_FIREBASE_API_KEY = "AIzaSyBUZHdpAeAwCXUNHbCX2dICA_GD85BEBrg"

SIGN_IN_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
REFRESH_URL = "https://securetoken.googleapis.com/v1/token"

#: Scopes are an OAuth concept; recorded on firebase credentials only so
#: `whoami` output stays meaningful. A Firebase ID token carries the
#: user's full session (no scope narrowing).
FIREBASE_SCOPES_NOTE = "full-session (Firebase ID token)"


class FirebaseLoginError(CloudError):
    """Firebase sign-in failed (bad credentials, disabled, throttled...)."""


#: Identity Toolkit error code → actionable message. Codes may arrive
#: suffixed (e.g. "TOO_MANY_ATTEMPTS_TRY_LATER : ..."), so match prefixes.
_ERROR_MESSAGES = {
    "EMAIL_NOT_FOUND": (
        "No account exists for that email address. Check the spelling, or "
        "sign up in the web app first."
    ),
    "INVALID_PASSWORD": (
        "Incorrect password. Note: accounts created with Google sign-in "
        "have no password — set one via the web app's password reset, or "
        "wait for browser OAuth login (plain `showrunner login`) "
        "to reach production."
    ),
    "INVALID_LOGIN_CREDENTIALS": (
        "Email or password is incorrect. Note: accounts created with "
        "Google sign-in have no password — set one via the web app's "
        "password reset, or wait for browser OAuth login "
        "(plain `showrunner login`) to reach production."
    ),
    "USER_DISABLED": (
        "This account has been disabled by an administrator."
    ),
    "TOO_MANY_ATTEMPTS_TRY_LATER": (
        "Too many failed sign-in attempts — Firebase has temporarily "
        "locked this account. Wait a few minutes and try again."
    ),
}


def _friendly_error(resp) -> FirebaseLoginError:
    """Map an Identity Toolkit error response to an actionable message."""
    try:
        code = str(resp.json().get("error", {}).get("message", ""))
    except Exception:
        code = ""
    for prefix, message in _ERROR_MESSAGES.items():
        if code.startswith(prefix):
            return FirebaseLoginError(message)
    return FirebaseLoginError(
        f"Firebase sign-in failed (HTTP {resp.status_code}"
        + (f": {code}" if code else "")
        + ")."
    )


def sign_in(
    server_url: str,
    email: str,
    password: str,
    *,
    api_key: str = DEFAULT_FIREBASE_API_KEY,
    transport=None,
) -> Credentials:
    """Exchange email+password for a Firebase ID token; return Credentials.

    The returned credentials are NOT saved — the caller persists them via
    CredentialStore (same contract as :func:`showrunner.cloud.auth.login`).
    """
    import httpx  # noqa: PLC0415 — optional dep, lazy import

    if not api_key:
        raise FirebaseLoginError(
            "No Firebase API key configured. Set `cloud.firebase_api_key` "
            "in .showrunner.yaml (the web API key of the server's Firebase "
            "project)."
        )
    with httpx.Client(transport=transport, timeout=30.0) as client:
        resp = client.post(
            SIGN_IN_URL,
            params={"key": api_key},
            json={"email": email, "password": password, "returnSecureToken": True},
        )
    if resp.status_code != 200:
        raise _friendly_error(resp)
    payload = resp.json()
    expires_in = payload.get("expiresIn")
    return Credentials(
        server_url=server_url.rstrip("/"),
        access_token=payload["idToken"],
        refresh_token=payload.get("refreshToken"),
        expires_at=(time.time() + float(expires_in)) if expires_in else None,
        scopes=FIREBASE_SCOPES_NOTE,
        method="firebase",
        firebase_api_key=api_key,
        source="login",
    )


def refresh(creds: Credentials, *, transport=None) -> Credentials:
    """Refresh a Firebase ID token via the secure token endpoint.

    Rotates the stored refresh token when Google returns a new one.
    Raises NotLoggedInError when the refresh token is gone or rejected
    (expired/revoked) — the user must `showrunner login` again.
    """
    import httpx  # noqa: PLC0415 — optional dep, lazy import

    if not creds.refresh_token:
        raise NotLoggedInError(
            "Session expired and no refresh token is available. "
            "Run `showrunner login` to authenticate again."
        )
    api_key = creds.firebase_api_key or DEFAULT_FIREBASE_API_KEY
    with httpx.Client(transport=transport, timeout=30.0) as client:
        resp = client.post(
            REFRESH_URL,
            params={"key": api_key},
            data={
                "grant_type": "refresh_token",
                "refresh_token": creds.refresh_token,
            },
        )
    if resp.status_code != 200:
        try:
            code = str(resp.json().get("error", {}).get("message", ""))
        except Exception:
            code = f"http_{resp.status_code}"
        raise NotLoggedInError(
            f"Your session has expired ({code or resp.status_code}). "
            "Run `showrunner login` to authenticate again."
        )
    payload = resp.json()
    expires_in = payload.get("expires_in")
    return Credentials(
        server_url=creds.server_url,
        access_token=payload["id_token"],
        # Rotation: keep the old refresh token if Google ever omits one.
        refresh_token=payload.get("refresh_token") or creds.refresh_token,
        expires_at=(time.time() + float(expires_in)) if expires_in else None,
        scopes=creds.scopes,
        method="firebase",
        firebase_api_key=api_key,
        source="login",
    )


def decode_id_token(id_token: str) -> dict:
    """Decode a Firebase ID token's payload claims locally (no signature
    verification — this is for display only; the SERVER verifies tokens).
    """
    try:
        payload_b64 = id_token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)  # restore padding
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception as e:
        raise FirebaseLoginError(
            f"Could not decode the stored ID token locally ({e})."
        ) from e
