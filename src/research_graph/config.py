"""Конфигурация приложения.

Значения читаются (по убыванию приоритета) из аргументов конструктора,
переменных окружения с префиксом ``RG_``, файла ``.env`` в текущей директории
и, наконец, из значений по умолчанию.
"""

import logging
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogFormat = Literal["text", "json"]

VALID_LOG_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"})

_MASK = "****"
_VISIBLE_TAIL = 4


class Settings(BaseSettings):
    """Настройки приложения."""

    model_config = SettingsConfigDict(
        env_prefix="RG_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_default=True,
    )

    github_token: str | None = Field(
        default=None,
        description="Персональный токен GitHub API (необязателен).",
    )
    data_dir: Path = Field(
        default=Path("data"),
        description="Корневая директория для данных проекта.",
    )
    log_level: str = Field(
        default="INFO",
        description="Уровень логирования: DEBUG, INFO, WARNING, ERROR, CRITICAL.",
    )
    log_format: LogFormat = Field(
        default="text",
        description="Формат логов: text (человекочитаемый) или json (одна JSON-строка на запись).",
    )
    request_timeout: float = Field(
        default=10.0,
        gt=0,
        le=300,
        description="Таймаут HTTP-запросов в секундах, (0; 300].",
    )
    max_concurrency: int = Field(
        default=4,
        ge=1,
        le=64,
        description="Максимальное число параллельных запросов, [1; 64].",
    )

    @field_validator("github_token", mode="before")
    @classmethod
    def _empty_token_is_none(cls, value: object) -> object:
        """Пустая строка в окружении (``RG_GITHUB_TOKEN=``) означает «токена нет»."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().upper()
        if normalized not in VALID_LOG_LEVELS:
            allowed = ", ".join(sorted(VALID_LOG_LEVELS))
            msg = f"unknown log level {value!r}; expected one of: {allowed}"
            raise ValueError(msg)
        return normalized

    @property
    def log_level_value(self) -> int:
        """Числовое значение уровня логирования для модуля ``logging``."""
        return logging.getLevelNamesMapping()[self.log_level]

    @property
    def masked_github_token(self) -> str | None:
        """Токен в безопасном для вывода виде (``ghp_****abcd``) или ``None``."""
        return mask_secret(self.github_token)

    def ensure_data_dir(self) -> Path:
        """Создаёт ``data_dir`` (со всеми родителями), если её нет, и возвращает путь."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir


def mask_secret(secret: str | None) -> str | None:
    """Маскирует секрет, оставляя видимыми префикс до ``_`` и последние 4 символа.

    >>> mask_secret("ghp_1234567890abcd")
    'ghp_****abcd'
    >>> mask_secret("short")
    '****'
    """
    if secret is None:
        return None
    # Слишком короткий секрет целиком скрываем: хвост выдал бы большую его часть.
    if len(secret) <= _VISIBLE_TAIL * 3:
        return _MASK
    prefix, sep, _ = secret.partition("_")
    head = prefix + sep if sep and len(prefix) <= _VISIBLE_TAIL else ""
    return f"{head}{_MASK}{secret[-_VISIBLE_TAIL:]}"


def get_settings() -> Settings:
    """Загружает и возвращает настройки приложения."""
    return Settings()
