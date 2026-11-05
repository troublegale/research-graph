"""Общие фикстуры тестов."""

import logging
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest_plugins = ["tests.db_fixtures"]


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Изолирует тесты от локального .env и реального окружения."""
    for key in list(os.environ):
        if key.startswith("RG_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def restore_root_logger() -> Iterator[None]:
    """Возвращает корневой логгер в исходное состояние после теста."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for handler in list(root.handlers):
        if handler not in handlers:
            handler.close()
    root.handlers[:] = handlers
    root.setLevel(level)
