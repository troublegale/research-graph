"""Тесты настройки логирования."""

import json
import logging
import sys

import pytest

from research_graph.logging_setup import NOISY_LOGGERS, JsonFormatter, setup_logging


def test_repeated_setup_does_not_duplicate_handlers() -> None:
    setup_logging("INFO")
    setup_logging("INFO")
    root = logging.getLogger()
    assert len(root.handlers) == 1


def test_logs_go_to_stderr_not_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging("INFO")
    logging.getLogger("research_graph.test").info("hello stderr")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "hello stderr" in captured.err


def test_text_format_contains_required_parts(capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging("warning")
    logging.getLogger("research_graph.demo").warning("something happened")
    line = capsys.readouterr().err.strip()
    parts = [part.strip() for part in line.split("|")]
    assert len(parts) == 4
    timestamp, level, name, message = parts
    assert timestamp[:4].isdigit()
    assert level == "WARNING"
    assert name == "research_graph.demo"
    assert message == "something happened"


def test_level_filters_messages(capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging("ERROR")
    log = logging.getLogger("research_graph.filter")
    log.info("hidden")
    log.error("visible")
    err = capsys.readouterr().err
    assert "hidden" not in err
    assert "visible" in err


def test_noisy_loggers_are_silenced() -> None:
    setup_logging("DEBUG")
    for name in NOISY_LOGGERS:
        assert logging.getLogger(name).getEffectiveLevel() == logging.WARNING
    setup_logging("ERROR")
    for name in NOISY_LOGGERS:
        assert logging.getLogger(name).getEffectiveLevel() == logging.ERROR


def test_unknown_level_raises() -> None:
    with pytest.raises(ValueError, match="unknown log level"):
        setup_logging("VERBOSE")


def test_json_format_emits_one_object_per_line(capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging("INFO", fmt="json")
    log = logging.getLogger("research_graph.json")
    log.info("первое сообщение %s", "ok")
    log.warning("second", extra={"repo": "octo/cat", "stars": 42})
    lines = capsys.readouterr().err.strip().splitlines()
    assert len(lines) == 2

    first, second = (json.loads(line) for line in lines)
    assert set(first) == {"timestamp", "level", "logger", "message"}
    assert first["level"] == "INFO"
    assert first["logger"] == "research_graph.json"
    assert first["message"] == "первое сообщение ok"
    assert first["timestamp"].endswith("+00:00")

    assert second["level"] == "WARNING"
    assert second["repo"] == "octo/cat"
    assert second["stars"] == 42


def test_json_formatter_serializes_exceptions_and_stack() -> None:
    formatter = JsonFormatter()
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = logging.LogRecord(
            "research_graph.err", logging.ERROR, __file__, 1, "failed", None, sys.exc_info()
        )
    record.stack_info = "Stack (most recent call last):\n  frame"
    payload = json.loads(formatter.format(record))
    assert payload["message"] == "failed"
    assert "RuntimeError: boom" in payload["exception"]
    assert "frame" in payload["stack"]


def test_json_formatter_handles_non_serializable_extra() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
    record.payload = {1, 2}
    record._private = "skip me"
    data = json.loads(JsonFormatter().format(record))
    assert data["payload"] == str({1, 2})
    assert "_private" not in data
