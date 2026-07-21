"""Showrunner cloud — login + API client for SocialGPT's public API.

Optional dependency group: `pip install showrunner[cloud]` (httpx).
`keyring` is an additional optional nicety for OS-keychain credential
storage; without it credentials fall back to a 0600 file under
`~/.showrunner/`.

Modules (all lazy-import httpx so the rest of showrunner never needs it):

- :mod:`showrunner.cloud.auth` — OAuth 2.1 PKCE loopback login flow
  (RFC 8252 native-app flow against the server's authorization server).
- :mod:`showrunner.cloud.firebase` — Firebase email/password login via
  Google's public Identity Toolkit API (the mode that works against
  today's production server; see DEFAULT_AUTH_METHOD).
- :mod:`showrunner.cloud.credentials` — token storage (OS keyring or
  0600 credentials file) + the ``SHOWRUNNER_TOKEN`` CI escape hatch.
- :mod:`showrunner.cloud.client` — thin authenticated httpx wrapper
  with one automatic refresh-and-retry on 401.
"""

from __future__ import annotations

#: Default cloud server. Override with `--server` or `cloud.server_url`
#: in .showrunner.yaml.
DEFAULT_SERVER_URL = "https://api.gpt.social"

#: Default `showrunner login` method. "oauth" (browser PKCE) — correct
#: once the server's OAuth chain deploys (scrollmark/showrunner#55 now
#: covers verification/docs). Until then, production only accepts
#: Firebase ID tokens: users log in with `showrunner login
#: --with-password` (or set `cloud.auth_method: firebase` in
#: .showrunner.yaml). An OAuth attempt against a server without the
#: chain gets an "Unknown OAuth client" error, which the CLI maps to a
#: hint suggesting --with-password.
DEFAULT_AUTH_METHOD = "oauth"

AUTH_METHODS = ("firebase", "oauth")


def _cloud_cfg(config) -> dict:
    if config is None:
        return {}
    return config.provider_config.get("cloud", {}) or {}


def resolve_auth_method(config=None, override: str | None = None) -> str:
    """Resolve the login method: CLI flag > cloud.auth_method > default."""
    method = override or _cloud_cfg(config).get("auth_method") or DEFAULT_AUTH_METHOD
    method = str(method)
    if method not in AUTH_METHODS:
        raise ValueError(
            f"Unknown cloud.auth_method {method!r} — expected one of "
            f"{', '.join(AUTH_METHODS)}."
        )
    return method


def resolve_firebase_api_key(config=None, override: str | None = None) -> str:
    """Resolve the Firebase web API key: flag > config > shipped default."""
    from showrunner.cloud.firebase import DEFAULT_FIREBASE_API_KEY  # noqa: PLC0415

    key = override or _cloud_cfg(config).get("firebase_api_key")
    return str(key) if key else DEFAULT_FIREBASE_API_KEY


def resolve_server_url(config=None, override: str | None = None) -> str:
    """Resolve the cloud server URL: CLI flag > config > default.

    `config` is a :class:`showrunner.config.Config`; the `cloud:` block of
    .showrunner.yaml lands in `config.provider_config["cloud"]`.
    """
    if override:
        return override.rstrip("/")
    if config is not None:
        cloud_cfg = config.provider_config.get("cloud", {}) or {}
        url = cloud_cfg.get("server_url")
        if url:
            return str(url).rstrip("/")
    return DEFAULT_SERVER_URL
