"""CLI cloud commands: login / logout / whoami (human + --json)."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

httpx = pytest.importorskip("httpx", reason="cloud extra (httpx) not installed")

from showrunner.cli.main import cli  # noqa: E402
from showrunner.cloud.credentials import Credentials, CredentialStore  # noqa: E402

SERVER = "https://api.gpt.social"  # the built-in default


@pytest.fixture
def cred_file(tmp_path, monkeypatch):
    """Route the default CredentialStore to a tmp file (never the real
    keyring / home dir) for every CLI invocation in the test."""
    path = tmp_path / "credentials.json"
    monkeypatch.setattr(
        "showrunner.cloud.credentials.default_credentials_path", lambda: path
    )
    monkeypatch.setattr(CredentialStore, "_keyring", lambda self: None)
    monkeypatch.delenv("SHOWRUNNER_TOKEN", raising=False)
    return path


def _creds(**kw) -> Credentials:
    defaults = dict(
        server_url=SERVER, access_token="at-1", refresh_token="rt-1",
        expires_at=time.time() + 3600,
        scopes="analysis:read analysis:upload offline_access",
    )
    defaults.update(kw)
    return Credentials(**defaults)


def _login_patch(creds=None):
    return patch("showrunner.cloud.auth.login", return_value=creds or _creds())


# ── login ────────────────────────────────────────────────────────────


def test_login_saves_credentials(cred_file):
    with _login_patch() as mock_login:
        result = CliRunner().invoke(cli, ["login", "--method", "oauth"], catch_exceptions=False)
    assert result.exit_code == 0
    assert mock_login.call_args.args[0] == SERVER
    assert "Logged in to" in result.output
    saved = json.loads(cred_file.read_text())[SERVER]
    assert saved["access_token"] == "at-1"


def test_login_json_mode(cred_file):
    with _login_patch():
        result = CliRunner().invoke(cli, ["login", "--method", "oauth", "--json"], catch_exceptions=False)
    assert result.exit_code == 0
    doc = json.loads(result.output)
    assert doc["status"] == "logged_in"
    assert doc["server_url"] == SERVER
    assert doc["scopes"] == "analysis:read analysis:upload offline_access"


def test_login_respects_server_flag(cred_file):
    with _login_patch(_creds(server_url="https://staging.test")) as mock_login:
        result = CliRunner().invoke(
            cli, ["login", "--method", "oauth", "--server", "https://staging.test"],
            catch_exceptions=False
        )
    assert result.exit_code == 0
    assert mock_login.call_args.args[0] == "https://staging.test"


def test_login_passes_no_browser(cred_file):
    with _login_patch() as mock_login:
        CliRunner().invoke(cli, ["login", "--method", "oauth", "--no-browser"],
                           catch_exceptions=False)
    assert mock_login.call_args.kwargs["no_browser"] is True


def test_login_failure_json(cred_file):
    from showrunner.cloud.auth import LoginError

    with patch("showrunner.cloud.auth.login", side_effect=LoginError("denied")):
        result = CliRunner().invoke(cli, ["login", "--method", "oauth", "--json"])
    assert result.exit_code == 1
    doc = json.loads(result.output)
    assert doc["error"] == "login_failed"
    assert "denied" in doc["message"]


def test_login_failure_human(cred_file):
    from showrunner.cloud.auth import LoginError

    with patch("showrunner.cloud.auth.login", side_effect=LoginError("denied")):
        result = CliRunner().invoke(cli, ["login", "--method", "oauth"])
    assert result.exit_code != 0
    assert "denied" in result.output


# ── logout ───────────────────────────────────────────────────────────


def test_logout_revokes_and_clears(cred_file):
    CredentialStore().save(_creds())
    with patch("showrunner.cloud.auth.revoke", return_value=True) as mock_revoke:
        result = CliRunner().invoke(cli, ["logout"], catch_exceptions=False)
    assert result.exit_code == 0
    assert mock_revoke.called
    assert "Logged out" in result.output
    assert CredentialStore().load(SERVER) is None


def test_logout_json(cred_file):
    CredentialStore().save(_creds())
    with patch("showrunner.cloud.auth.revoke", return_value=False):
        result = CliRunner().invoke(cli, ["logout", "--json"], catch_exceptions=False)
    doc = json.loads(result.output)
    assert doc == {"status": "logged_out", "server_url": SERVER, "revoked": False}


def test_logout_when_not_logged_in(cred_file):
    with patch("showrunner.cloud.auth.revoke") as mock_revoke:
        result = CliRunner().invoke(cli, ["logout"], catch_exceptions=False)
    assert result.exit_code == 0
    assert not mock_revoke.called
    assert "no stored credentials" in result.output


# ── whoami ───────────────────────────────────────────────────────────


def _client_patch(user=None, status=200):
    api = MagicMock()
    api.__enter__ = MagicMock(return_value=api)
    api.__exit__ = MagicMock(return_value=None)
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = user or {}
    api.get.return_value = resp
    return patch("showrunner.cloud.client.CloudClient", return_value=api), api


def test_whoami_logged_in(cred_file):
    CredentialStore().save(_creds())
    client_patch, api = _client_patch(user={"email": "john@scrollmark.com"})
    with client_patch:
        result = CliRunner().invoke(cli, ["whoami"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "Logged in to" in result.output
    assert "john@scrollmark.com" in result.output
    api.get.assert_called_once_with("/api/v1/me")


def test_whoami_json(cred_file):
    CredentialStore().save(_creds())
    client_patch, _ = _client_patch(user={"email": "john@scrollmark.com"})
    with client_patch:
        result = CliRunner().invoke(cli, ["whoami", "--json"], catch_exceptions=False)
    doc = json.loads(result.output)
    assert doc["logged_in"] is True
    assert doc["server_url"] == SERVER
    assert doc["token_source"] == "file"
    assert doc["user"] == {"email": "john@scrollmark.com"}


def test_whoami_not_logged_in(cred_file):
    result = CliRunner().invoke(cli, ["whoami"])
    assert result.exit_code == 1
    assert "Not logged in" in result.output
    assert "showrunner login" in result.output


def test_whoami_not_logged_in_json(cred_file):
    result = CliRunner().invoke(cli, ["whoami", "--json"])
    assert result.exit_code == 1
    doc = json.loads(result.output)
    assert doc == {"logged_in": False, "server_url": SERVER}


def test_whoami_degrades_when_server_unreachable(cred_file):
    CredentialStore().save(_creds())
    api = MagicMock()
    api.__enter__ = MagicMock(return_value=api)
    api.__exit__ = MagicMock(return_value=None)
    api.get.side_effect = RuntimeError("connection refused")
    with patch("showrunner.cloud.client.CloudClient", return_value=api):
        result = CliRunner().invoke(cli, ["whoami", "--json"], catch_exceptions=False)
    assert result.exit_code == 0
    doc = json.loads(result.output)
    assert doc["logged_in"] is True
    assert doc["user"] is None
    assert "connection refused" in doc["api_error"]


def test_whoami_env_token_source(cred_file, monkeypatch):
    monkeypatch.setenv("SHOWRUNNER_TOKEN", "ci-token")
    client_patch, _ = _client_patch(user={"email": "ci@scrollmark.com"})
    with client_patch:
        result = CliRunner().invoke(cli, ["whoami", "--json"], catch_exceptions=False)
    doc = json.loads(result.output)
    assert doc["logged_in"] is True
    assert doc["token_source"] == "env"
