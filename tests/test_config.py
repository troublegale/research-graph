"""Тесты конфигурации."""

import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from research_graph.config import Settings, get_settings, mask_secret


def test_defaults_without_env() -> None:
    settings = get_settings()
    assert settings.github_token is None
    assert settings.data_dir == Path("data")
    assert settings.log_level == "INFO"
    assert settings.log_format == "text"
    assert settings.request_timeout == 10.0
    assert settings.max_concurrency == 4


def test_settings_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RG_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("RG_MAX_CONCURRENCY", "16")
    monkeypatch.setenv("RG_REQUEST_TIMEOUT", "2.5")
    monkeypatch.setenv("RG_DATA_DIR", "custom/dir")
    monkeypatch.setenv("RG_LOG_FORMAT", "json")
    settings = Settings()
    assert settings.log_level == "DEBUG"
    assert settings.max_concurrency == 16
    assert settings.request_timeout == 2.5
    assert settings.data_dir == Path("custom") / "dir"
    assert settings.log_format == "json"


def test_variables_without_prefix_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_CONCURRENCY", "32")
    assert Settings().max_concurrency == 4


def test_settings_read_from_dotenv(tmp_path: Path) -> None:
    # isolated_env уже сделал tmp_path текущей директорией.
    (tmp_path / ".env").write_text("RG_MAX_CONCURRENCY=8\nRG_LOG_LEVEL=warning\n", encoding="utf-8")
    settings = Settings()
    assert settings.max_concurrency == 8
    assert settings.log_level == "WARNING"


def test_env_has_priority_over_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("RG_MAX_CONCURRENCY=8\n", encoding="utf-8")
    monkeypatch.setenv("RG_MAX_CONCURRENCY", "12")
    assert Settings().max_concurrency == 12


@pytest.mark.parametrize("value", ["0", "-1", "65", "many"])
def test_rejects_invalid_concurrency(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("RG_MAX_CONCURRENCY", value)
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize("value", ["0", "-5", "301"])
def test_rejects_invalid_timeout(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("RG_REQUEST_TIMEOUT", value)
    with pytest.raises(ValidationError):
        Settings()


def test_rejects_unknown_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RG_LOG_LEVEL", "LOUD")
    with pytest.raises(ValidationError, match="unknown log level"):
        Settings()


def test_rejects_unknown_log_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RG_LOG_FORMAT", "xml")
    with pytest.raises(ValidationError):
        Settings()


def test_non_string_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(log_level=10)  # type: ignore[arg-type]  # проверяем именно неверный тип


def test_log_level_is_normalized() -> None:
    settings = Settings(log_level=" debug ")
    assert settings.log_level == "DEBUG"
    assert settings.log_level_value == logging.DEBUG


def test_empty_token_is_treated_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RG_GITHUB_TOKEN", "  ")
    settings = Settings()
    assert settings.github_token is None
    assert settings.masked_github_token is None


def test_token_is_masked() -> None:
    settings = Settings(github_token="ghp_supersecretvalue")
    assert settings.masked_github_token == "ghp_****alue"


@pytest.mark.parametrize(
    ("secret", "expected"),
    [
        (None, None),
        ("", "****"),
        ("short", "****"),
        ("ghp_1234567890abcd", "ghp_****abcd"),
        ("github_pat_0123456789abcdef", "****cdef"),  # длинный префикс не раскрываем
        ("plainsecretwithoutprefix", "****efix"),
    ],
)
def test_mask_secret(secret: str | None, expected: str | None) -> None:
    assert mask_secret(secret) == expected


def test_ensure_data_dir_creates_nested_directory(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "data"
    settings = Settings(data_dir=target)
    assert not target.exists()
    assert settings.ensure_data_dir() == target
    assert target.is_dir()
    # Повторный вызов не падает.
    assert settings.ensure_data_dir() == target
