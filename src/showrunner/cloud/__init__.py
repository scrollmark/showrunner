"""Showrunner cloud — login + API client for SocialGPT's public API.

Optional dependency group: `pip install showrunner[cloud]` (httpx).
`keyring` is an additional optional nicety for OS-keychain credential
storage; without it credentials fall back to a 0600 file under
`~/.showrunner/`.

Modules (all lazy-import httpx so the rest of showrunner never needs it):

- :mod:`showrunner.cloud.auth` — OAuth 2.1 PKCE loopback login flow
  (RFC 8252 native-app flow against the server's authorization server).
- :mod:`showrunner.cloud.credentials` — token storage (OS keyring or
  0600 credentials file) + the ``SHOWRUNNER_TOKEN`` CI escape hatch.
- :mod:`showrunner.cloud.client` — thin authenticated httpx wrapper
  with one automatic refresh-and-retry on 401.
"""

from __future__ import annotations

#: Default cloud server. Override with `--server` or `cloud.server_url`
#: in .showrunner.yaml.
DEFAULT_SERVER_URL = "https://api.gpt.social"


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
