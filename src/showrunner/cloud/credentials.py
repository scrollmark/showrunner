"""Credential storage for showrunner cloud login.

Storage order of preference:

1. ``SHOWRUNNER_TOKEN`` env var — CI escape hatch. Used as a bearer
   token directly; storage is never read or written for it and there is
   no refresh token.
2. OS keyring (``pip install keyring``) — one entry per server URL under
   the ``showrunner`` service.
3. ``~/.showrunner/credentials.json`` — created with mode 0600 (dir
   0700), keyed by server URL, supports multiple servers.

No network code lives here (see :mod:`showrunner.cloud.auth` for the
token endpoint calls); this module is importable without httpx.
"""

from __future__ import annotations

import json
import os
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path

ENV_TOKEN = "SHOWRUNNER_TOKEN"
KEYRING_SERVICE = "showrunner"

#: Refresh this many seconds before the recorded expiry to absorb clock
#: skew and request latency.
EXPIRY_SKEW_SECONDS = 60


class CloudError(Exception):
    """Base class for showrunner cloud errors."""


class NotLoggedInError(CloudError):
    """No usable credentials — the user must run `showrunner login`."""

    def __init__(self, message: str | None = None):
        super().__init__(
            message or "Not logged in. Run `showrunner login` to authenticate."
        )


@dataclass
class Credentials:
    """A stored token set for one cloud server."""

    server_url: str
    access_token: str
    refresh_token: str | None = None
    #: Unix epoch seconds when the access token expires (None = unknown).
    expires_at: float | None = None
    scopes: str | None = None
    token_type: str = "Bearer"
    #: Where these credentials came from: "env" | "keyring" | "file" |
    #: "login" (fresh from the token endpoint). Not serialized.
    source: str = field(default="login", compare=False)

    @property
    def expired(self) -> bool:
        """True when the access token is past (or within skew of) expiry."""
        if self.expires_at is None:
            return False
        return time.time() >= (self.expires_at - EXPIRY_SKEW_SECONDS)

    def to_dict(self) -> dict:
        return {
            "server_url": self.server_url,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "scopes": self.scopes,
            "token_type": self.token_type,
        }

    @classmethod
    def from_dict(cls, d: dict, *, source: str = "file") -> Credentials:
        return cls(
            server_url=d["server_url"],
            access_token=d["access_token"],
            refresh_token=d.get("refresh_token"),
            expires_at=d.get("expires_at"),
            scopes=d.get("scopes"),
            token_type=d.get("token_type", "Bearer"),
            source=source,
        )


def default_credentials_path() -> Path:
    return Path.home() / ".showrunner" / "credentials.json"


class CredentialStore:
    """Loads/saves :class:`Credentials`, preferring the OS keyring.

    `use_keyring=None` (default) auto-detects: use keyring when the
    module imports and works, else fall back to the credentials file.
    Pass `path` to relocate the fallback file (tests use tmp_path).
    """

    def __init__(self, path: Path | None = None, use_keyring: bool | None = None):
        self.path = path or default_credentials_path()
        self._use_keyring = use_keyring

    # ── keyring backend ──────────────────────────────────────────────

    def _keyring(self):
        """Return the keyring module, or None when unavailable/disabled."""
        if self._use_keyring is False:
            return None
        try:
            import keyring  # noqa: PLC0415 — optional dep, lazy import
            return keyring
        except ImportError:
            if self._use_keyring is True:
                raise
            return None

    # ── file backend ─────────────────────────────────────────────────

    def _read_file(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_file(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.parent.chmod(stat.S_IRWXU)  # 0700
        except OSError:
            pass
        # Create-then-chmod has a window where the file is group-readable;
        # open with restrictive mode from the start instead.
        fd = os.open(
            self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        try:
            self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600, even if pre-existing
        except OSError:
            pass

    # ── public API ───────────────────────────────────────────────────

    def load(self, server_url: str) -> Credentials | None:
        """Load credentials for `server_url`.

        ``SHOWRUNNER_TOKEN`` wins unconditionally (CI escape hatch — no
        refresh token, storage untouched).
        """
        env_token = os.environ.get(ENV_TOKEN)
        if env_token:
            return Credentials(
                server_url=server_url, access_token=env_token, source="env"
            )
        server_url = server_url.rstrip("/")

        kr = self._keyring()
        if kr is not None:
            try:
                blob = kr.get_password(KEYRING_SERVICE, server_url)
            except Exception:
                blob = None
            if blob:
                try:
                    return Credentials.from_dict(json.loads(blob), source="keyring")
                except (json.JSONDecodeError, KeyError):
                    pass

        entry = self._read_file().get(server_url)
        if entry:
            try:
                return Credentials.from_dict(entry, source="file")
            except KeyError:
                return None
        return None

    def save(self, creds: Credentials) -> None:
        """Persist credentials (keyring when available, else 0600 file).

        Env-sourced credentials are never persisted.
        """
        if creds.source == "env":
            return
        server_url = creds.server_url.rstrip("/")
        creds.server_url = server_url

        kr = self._keyring()
        if kr is not None:
            try:
                kr.set_password(
                    KEYRING_SERVICE, server_url, json.dumps(creds.to_dict())
                )
                return
            except Exception:
                pass  # fall through to file storage

        data = self._read_file()
        data[server_url] = creds.to_dict()
        self._write_file(data)

    def backend_description(self) -> str:
        """Human-readable description of where credentials are persisted."""
        return "OS keyring" if self._keyring() is not None else str(self.path)

    def clear(self, server_url: str) -> None:
        """Remove stored credentials for `server_url` from all backends."""
        server_url = server_url.rstrip("/")
        kr = self._keyring()
        if kr is not None:
            try:
                kr.delete_password(KEYRING_SERVICE, server_url)
            except Exception:
                pass
        data = self._read_file()
        if server_url in data:
            del data[server_url]
            self._write_file(data)
