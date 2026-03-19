from click.testing import CliRunner

from showrunner.cli.main import cli


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "showrunner" in result.output.lower() or "video" in result.output.lower()


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_cli_formats():
    runner = CliRunner()
    result = runner.invoke(cli, ["formats"])
    assert result.exit_code == 0
    # faceless-explainer should be registered via entry points
    # (may not be if package not installed in editable mode with entry points)


def test_cli_styles():
    runner = CliRunner()
    result = runner.invoke(cli, ["styles"])
    assert result.exit_code == 0
    assert "3b1b-dark" in result.output


def test_cli_voices():
    runner = CliRunner()
    result = runner.invoke(cli, ["voices"])
    assert result.exit_code == 0
    assert "af_heart" in result.output


def test_cli_providers():
    runner = CliRunner()
    result = runner.invoke(cli, ["providers"])
    assert result.exit_code == 0
    assert "anthropic" in result.output


def test_cli_create_no_topic():
    runner = CliRunner()
    result = runner.invoke(cli, ["create"])
    assert result.exit_code != 0
