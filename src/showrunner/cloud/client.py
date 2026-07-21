"""Authenticated httpx wrapper for the showrunner cloud API.

Every request carries ``Authorization: Bearer`` and
``X-Client-Surface: cli``. Expired access tokens are refreshed
proactively (using the stored expiry) and reactively: exactly one
automatic refresh-and-retry on a 401 response. Refresh rotation is
persisted through the CredentialStore.

httpx is imported lazily (optional `[cloud]` dep group).
"""

from __future__ import annotations

from showrunner.cloud import auth
from showrunner.cloud.credentials import (
    Credentials,
    CredentialStore,
    NotLoggedInError,
)


class CloudClient:
    """Thin authenticated API client bound to one server URL."""

    def __init__(
        self,
        server_url: str,
        *,
        store: CredentialStore | None = None,
        credentials: Credentials | None = None,
        transport=None,
        timeout: float = 30.0,
    ):
        import httpx  # noqa: PLC0415 — optional dep, lazy import

        self.server_url = server_url.rstrip("/")
        self.store = store or CredentialStore()
        self._creds = credentials
        self._client = httpx.Client(
            base_url=self.server_url, transport=transport, timeout=timeout
        )
        self._transport = transport

    # ── credentials ──────────────────────────────────────────────────

    @property
    def credentials(self) -> Credentials:
        if self._creds is None:
            self._creds = self.store.load(self.server_url)
        if self._creds is None:
            raise NotLoggedInError()
        return self._creds

    def _refresh(self) -> None:
        """Refresh + persist rotation. Raises NotLoggedInError when unusable.

        Dispatches on the stored credentials' auth method: "firebase"
        refreshes against Google's secure token endpoint, anything else
        against the server's OAuth token endpoint.
        """
        creds = self.credentials
        if creds.source == "env":
            raise NotLoggedInError(
                "The SHOWRUNNER_TOKEN environment token was rejected (401) "
                "and cannot be refreshed. Provide a fresh token or unset it "
                "and run `showrunner login`."
            )
        if creds.method == "firebase":
            from showrunner.cloud import firebase  # noqa: PLC0415 — lazy

            self._creds = firebase.refresh(creds, transport=self._transport)
        else:
            self._creds = auth.refresh(creds, transport=self._transport)
        self.store.save(self._creds)

    def _headers(self) -> dict:
        creds = self.credentials
        return {
            "Authorization": f"{creds.token_type} {creds.access_token}",
            "X-Client-Surface": "cli",
        }

    # ── requests ─────────────────────────────────────────────────────

    def request(self, method: str, path: str, **kwargs):
        """Issue an authenticated request; one refresh-and-retry on 401."""
        creds = self.credentials
        if creds.expired and creds.source != "env":
            self._refresh()
        resp = self._client.request(method, path, headers=self._headers(), **kwargs)
        if resp.status_code == 401:
            self._refresh()  # raises NotLoggedInError if refresh impossible
            resp = self._client.request(
                method, path, headers=self._headers(), **kwargs
            )
        return resp

    def get(self, path: str, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs):
        return self.request("POST", path, **kwargs)

    def delete(self, path: str, **kwargs):
        return self.request("DELETE", path, **kwargs)

    # ── lifecycle ────────────────────────────────────────────────────

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> CloudClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
