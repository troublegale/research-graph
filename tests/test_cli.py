"""Тесты CLI."""

import json
import runpy
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from research_graph import __version__
from research_graph.cli import app

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_help_lists_both_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "version" in result.stdout
    assert "check-config" in result.stdout


def test_check_config_prints_summary() -> None:
    result = runner.invoke(app, ["check-config"])
    assert result.exit_code == 0
    assert "Configuration summary" in result.stdout
    assert "github_token" in result.stdout
    assert "not set" in result.stdout
    assert "max_concurrency" in result.stdout


def test_check_config_hides_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RG_GITHUB_TOKEN", "ghp_supersecretvalue")
    result = runner.invoke(app, ["check-config"])
    assert result.exit_code == 0
    assert "ghp_supersecretvalue" not in result.stdout
    assert "ghp_supersecretvalue" not in result.stderr
    assert "ghp_****alue" in result.stdout


def test_check_config_logs_to_stderr() -> None:
    result = runner.invoke(app, ["check-config"])
    assert "Configuration loaded" in result.stderr
    assert "Configuration loaded" not in result.stdout


def test_check_config_json_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RG_LOG_FORMAT", "json")
    result = runner.invoke(app, ["check-config"])
    assert result.exit_code == 0
    record = json.loads(result.stderr.strip().splitlines()[0])
    assert record["message"] == "Configuration loaded"


def test_check_config_creates_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "store"
    monkeypatch.setenv("RG_DATA_DIR", str(target))
    result = runner.invoke(app, ["check-config", "--create-data-dir"])
    assert result.exit_code == 0
    assert target.is_dir()
    assert "data_dir exists" in result.stdout


def test_check_config_reports_invalid_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RG_MAX_CONCURRENCY", "0")
    monkeypatch.setenv("RG_GITHUB_TOKEN", "ghp_supersecretvalue")
    result = runner.invoke(app, ["check-config"])
    assert result.exit_code == 2
    assert "RG_MAX_CONCURRENCY" in result.stderr
    assert "ghp_supersecretvalue" not in result.output


def test_no_args_shows_help() -> None:
    result = runner.invoke(app, [])
    assert "check-config" in result.output


def test_module_entry_point(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["research_graph", "version"])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("research_graph", run_name="__main__", alter_sys=True)
    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == __version__


def test_data_and_training_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alembic.config import Config

    from tests.db_fixtures import ROOT

    original_init = Config.__init__

    def project_config(self: Config, *args: object, **kwargs: object) -> None:
        original_init(self, str(ROOT / "alembic.ini"))
        self.set_main_option("script_location", str(ROOT / "migrations"))

    monkeypatch.setattr(Config, "__init__", project_config)
    assert runner.invoke(app, ["migrate"]).exit_code == 0
    assert runner.invoke(app, ["seed"]).exit_code == 0
    assert runner.invoke(app, ["import-data", "data/demo.csv", "--limit", "1"]).exit_code == 0
    result = runner.invoke(app, ["prepare-data", "data/demo.csv", "--size", "150"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["train", "--threads", "1", "--iterations", "2"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "artifacts/model.zip").is_file()


def test_serve_command(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    calls: list[object] = []
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs))
    assert runner.invoke(app, ["serve", "--port", "8001"]).exit_code == 0
    assert calls


def test_download_command_streams_expected_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io
    import urllib.request
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("all_regions.csv", "brand,name\nToyota,Corolla\n")
    payload = buffer.getvalue()
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(payload))
    result = runner.invoke(app, ["download-data"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "data/raw/all_regions.csv").read_text() == "brand,name\nToyota,Corolla\n"
    assert not (tmp_path / "data/raw/all_regions.zip.part").exists()
