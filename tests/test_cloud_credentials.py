"""Credential storage: file fallback (0600), fake keyring, env escape hatch."""

import json
import stat
import time

import pytest

from showrunner.cloud.credentials import (
    ENV_TOKEN,
    KEYRING_SERVICE,
    Credentials,
    CredentialStore,
    NotLoggedInError,
)

SERVER = "https://api.example.test"


def _creds(**kw) -> Credentials:
    defaults = dict(
        server_url=SERVER,
        access_token="at-1",
        refresh_token="rt-1",
        expires_at=time.time() + 3600,
        scopes="analysis:read analysis:upload offline_access",
    )
    defaults.update(kw)
    return Credentials(**defaults)


def _file_store(tmp_path) -> CredentialStore:
    return CredentialStore(path=tmp_path / "credentials.json", use_keyring=False)


# ── Credentials model ────────────────────────────────────────────────


def test_expired_false_when_fresh():
    assert not _creds().expired


def test_expired_true_past_expiry():
    assert _creds(expires_at=time.time() - 10).expired


def test_expired_true_within_skew():
    assert _creds(expires_at=time.time() + 30).expired  # < 60s skew


def test_expired_false_when_unknown():
    assert not _creds(expires_at=None).expired


def test_roundtrip_dict():
    creds = _creds()
    again = Credentials.from_dict(creds.to_dict())
    assert again == creds  # source excluded from comparison


def test_not_logged_in_error_message_mentions_login():
    assert "showrunner login" in str(NotLoggedInError())


# ── file backend ─────────────────────────────────────────────────────


def test_file_save_load_roundtrip(tmp_path):
    store = _file_store(tmp_path)
    store.save(_creds())
    loaded = store.load(SERVER)
    assert loaded is not None
    assert loaded.access_token == "at-1"
    assert loaded.refresh_token == "rt-1"
    assert loaded.source == "file"


def test_file_created_with_0600(tmp_path):
    store = _file_store(tmp_path)
    store.save(_creds())
    mode = stat.S_IMODE(store.path.stat().st_mode)
    assert mode == 0o600


def test_file_supports_multiple_servers(tmp_path):
    store = _file_store(tmp_path)
    store.save(_creds())
    store.save(_creds(server_url="https://staging.example.test", access_token="at-2"))
    assert store.load(SERVER).access_token == "at-1"
    assert store.load("https://staging.example.test").access_token == "at-2"


def test_load_missing_returns_none(tmp_path):
    assert _file_store(tmp_path).load(SERVER) is None


def test_load_corrupt_file_returns_none(tmp_path):
    store = _file_store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{not json")
    assert store.load(SERVER) is None


def test_clear_removes_entry(tmp_path):
    store = _file_store(tmp_path)
    store.save(_creds())
    store.clear(SERVER)
    assert store.load(SERVER) is None


def test_trailing_slash_normalized(tmp_path):
    store = _file_store(tmp_path)
    store.save(_creds(server_url=SERVER + "/"))
    assert store.load(SERVER) is not None
    assert store.load(SERVER + "/") is not None


# ── env escape hatch ─────────────────────────────────────────────────


def test_env_token_wins(tmp_path, monkeypatch):
    store = _file_store(tmp_path)
    store.save(_creds())
    monkeypatch.setenv(ENV_TOKEN, "ci-token")
    loaded = store.load(SERVER)
    assert loaded.access_token == "ci-token"
    assert loaded.source == "env"
    assert loaded.refresh_token is None
    assert not loaded.expired  # no expiry recorded for env tokens


def test_env_token_never_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_TOKEN, "ci-token")
    store = _file_store(tmp_path)
    store.save(store.load(SERVER))
    assert not store.path.exists()


# ── fake keyring backend ─────────────────────────────────────────────


class FakeKeyring:
    def __init__(self):
        self.data = {}

    def get_password(self, service, username):
        return self.data.get((service, username))

    def set_password(self, service, username, password):
        self.data[(service, username)] = password

    def delete_password(self, service, username):
        del self.data[(service, username)]


@pytest.fixture
def keyring_store(tmp_path, monkeypatch):
    fake = FakeKeyring()
    store = CredentialStore(path=tmp_path / "credentials.json", use_keyring=True)
    monkeypatch.setattr(CredentialStore, "_keyring", lambda self: fake)
    return store, fake


def test_keyring_save_load(keyring_store):
    store, fake = keyring_store
    store.save(_creds())
    assert (KEYRING_SERVICE, SERVER) in fake.data
    loaded = store.load(SERVER)
    assert loaded.access_token == "at-1"
    assert loaded.source == "keyring"
    assert not store.path.exists()  # keyring path never touches the file


def test_keyring_clear(keyring_store):
    store, fake = keyring_store
    store.save(_creds())
    store.clear(SERVER)
    assert store.load(SERVER) is None


def test_keyring_corrupt_blob_ignored(keyring_store):
    store, fake = keyring_store
    fake.set_password(KEYRING_SERVICE, SERVER, "{corrupt")
    assert store.load(SERVER) is None


def test_keyring_set_failure_falls_back_to_file(tmp_path, monkeypatch):
    class BrokenKeyring(FakeKeyring):
        def set_password(self, *a):
            raise RuntimeError("locked")

        def get_password(self, *a):
            return None

    store = CredentialStore(path=tmp_path / "credentials.json", use_keyring=True)
    monkeypatch.setattr(CredentialStore, "_keyring", lambda self: BrokenKeyring())
    store.save(_creds())
    assert store.path.exists()
    assert json.loads(store.path.read_text())[SERVER]["access_token"] == "at-1"


# ── server URL resolution (cloud.server_url config) ──────────────────


def test_resolve_server_url_default():
    from showrunner.cloud import DEFAULT_SERVER_URL, resolve_server_url

    assert resolve_server_url() == DEFAULT_SERVER_URL


def test_resolve_server_url_from_config():
    from showrunner.cloud import resolve_server_url
    from showrunner.config import Config

    config = Config.from_dict({"cloud": {"server_url": "https://staging.test/"}})
    assert resolve_server_url(config) == "https://staging.test"


def test_resolve_server_url_override_wins():
    from showrunner.cloud import resolve_server_url
    from showrunner.config import Config

    config = Config.from_dict({"cloud": {"server_url": "https://staging.test"}})
    assert resolve_server_url(config, override="https://flag.test/") == "https://flag.test"
