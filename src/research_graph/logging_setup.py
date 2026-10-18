"""Настройка логирования приложения.

Логи всегда пишутся в ``stderr``: ``stdout`` остаётся свободным для данных,
которые можно передать дальше по пайпу.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, Final, Literal

TEXT_FORMAT: Final = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT: Final = "%Y-%m-%d %H:%M:%S"

# Сторонние библиотеки, которые на DEBUG/INFO засоряют вывод.
NOISY_LOGGERS: Final = ("httpx", "httpcore", "urllib3", "asyncio", "sqlalchemy.engine")

# Стандартные атрибуты LogRecord — всё остальное считаем пользовательским `extra`.
_RESERVED_ATTRS: Final = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys() | {"message", "asctime"}
)


class JsonFormatter(logging.Formatter):
    """Форматирует запись лога как одну JSON-строку."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        for key, value in vars(record).items():
            if key not in _RESERVED_ATTRS and not key.startswith("_"):
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def _build_formatter(fmt: Literal["text", "json"]) -> logging.Formatter:
    if fmt == "json":
        return JsonFormatter()
    return logging.Formatter(TEXT_FORMAT, datefmt=DATE_FORMAT)


def setup_logging(level: str, fmt: Literal["text", "json"] = "text") -> None:
    """Настраивает корневой логгер.

    Повторный вызов безопасен: существующие обработчики удаляются,
    поэтому записи не задваиваются.

    :param level: имя уровня (``"INFO"``, ``"debug"`` и т. п.).
    :param fmt: ``"text"`` — человекочитаемый вывод, ``"json"`` — JSON Lines.
    :raises ValueError: если уровень неизвестен.
    """
    level_name = level.strip().upper()
    numeric_level = logging.getLevelNamesMapping().get(level_name)
    if numeric_level is None:
        msg = f"unknown log level: {level!r}"
        raise ValueError(msg)

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_build_formatter(fmt))
    root.addHandler(handler)
    root.setLevel(numeric_level)

    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(max(numeric_level, logging.WARNING))
