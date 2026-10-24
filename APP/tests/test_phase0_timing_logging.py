from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from starlette.requests import Request

from app.api import _request_timing_message
from app.core import (
    FACTORY_TIMING_LOG_BACKUP_COUNT,
    FACTORY_TIMING_LOG_FILENAME,
    FACTORY_TIMING_LOG_MAX_BYTES,
    FoundryError,
    configure_timing_logger,
)
from character_creation.service import CharacterCreationExecutionService


def _owned_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [
        handler
        for handler in logger.handlers
        if getattr(handler, "_factory_timing_handler", False)
    ]


def test_factory_timing_logger_is_idempotent_and_bounded(tmp_path):
    logger = configure_timing_logger(tmp_path / "logs")
    same_logger = configure_timing_logger(tmp_path / "logs")

    assert same_logger is logger
    assert logger.propagate is False
    handlers = _owned_handlers(logger)
    assert len(handlers) == 1
    handler = handlers[0]
    assert isinstance(handler, RotatingFileHandler)
    assert handler.maxBytes == FACTORY_TIMING_LOG_MAX_BYTES
    assert handler.backupCount == FACTORY_TIMING_LOG_BACKUP_COUNT
    assert handler.baseFilename.endswith(f"/{FACTORY_TIMING_LOG_FILENAME}")

    logger.info("request method=GET path=/api/session status=200 ms=1.25")
    handler.flush()
    lines = (tmp_path / "logs" / FACTORY_TIMING_LOG_FILENAME).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["level"] == "INFO"
    assert record["message"] == "request method=GET path=/api/session status=200 ms=1.25"


def _read_log(logs_dir: Path) -> list[dict[str, str]]:
    log_path = logs_dir / FACTORY_TIMING_LOG_FILENAME
    for handler in _owned_handlers(configure_timing_logger(logs_dir)):
        handler.flush()
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]


def _request(path: str, query: bytes = b"") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": query,
            "headers": [],
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1),
        }
    )


def test_request_timing_message_is_bounded_and_excludes_query_data():
    request = _request("/api/session", b"secret=must-not-be-logged")

    assert _request_timing_message(request, 200, 1.23456) == (
        "request method=GET path=/api/session status=200 ms=1.235"
    )
    assert "secret" not in _request_timing_message(request, 403, 2.0)
    assert "status=500" in _request_timing_message(request, 500, 3.0)


def test_run_provider_logs_existing_phases_without_provider_call(tmp_path):
    logs_dir = tmp_path / "logs"
    logger = configure_timing_logger(logs_dir)
    service = object.__new__(CharacterCreationExecutionService)
    service.timing_logger = logger
    service.provider = object()
    service._reject_dcc_provider_execution = lambda _run_id: None
    service.get = lambda _run_id: {"execution_mode": "STANDARD_API"}

    def fail_prompt(_run):
        raise FoundryError(
            "PROMPT_FAIL",
            "prompt failure",
        )

    service._provider_prompt = fail_prompt
    service._provider_fallback = lambda run, exc, *, timing_receipt: {
        "transport": {"timings": timing_receipt}
    }

    result = service._run_provider("run-without-provider")
    assert result["transport"]["timings"]["phases_ms"]
    records = _read_log(logs_dir)
    timing_messages = [record["message"] for record in records if record["message"].startswith("timing_receipt.")]
    assert len(timing_messages) == 1
    assert "timing_receipt.phases_ms={" in timing_messages[0]
    assert "factory_prompt_construction" in timing_messages[0]
    assert "PROMPT_FAIL" not in timing_messages[0]
    assert "prompt failure" not in timing_messages[0]
