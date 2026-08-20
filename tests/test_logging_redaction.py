"""PII-safe structured-logging tests (SOT-2804).

Guards the invariant that the logging layer never emits a child's Personal Context
values or health information, and that access/exception logs carry no request body.
"""

from __future__ import annotations

import io
import json
import logging

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from pcca.api.app import create_app
from pcca.logging_config import (
    JsonLogFormatter,
    RedactionFilter,
    configure_logging,
    redact_text,
)

# A distinctive health value we assert never survives into any log line.
_SECRET_HEALTH_VALUE = "peanut-allergy-EpiPen-1234567"


def _format(record: logging.LogRecord) -> str:
    """Run a record through the production filter + formatter, as a handler would."""

    RedactionFilter().filter(record)
    return JsonLogFormatter().format(record)


def _make_record(msg: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_redact_text_masks_email_and_phone() -> None:
    out = redact_text("contact parent@example.com or 090-1234-5678 now")
    assert "parent@example.com" not in out
    assert "090-1234-5678" not in out
    assert out.count("[REDACTED]") == 2


def test_filter_redacts_sensitive_extra_key() -> None:
    line = _format(_make_record("saved context", value=_SECRET_HEALTH_VALUE))
    payload = json.loads(line)
    assert _SECRET_HEALTH_VALUE not in line
    assert payload["value"] == "[REDACTED]"


def test_filter_masks_pii_in_message() -> None:
    payload = json.loads(_format(_make_record("login for kid@school.jp done")))
    assert "kid@school.jp" not in payload["message"]
    assert "[REDACTED]" in payload["message"]


def test_formatter_emits_cloud_logging_severity() -> None:
    record = _make_record("boom")
    record.levelname = "ERROR"
    record.levelno = logging.ERROR
    payload = json.loads(_format(record))
    assert payload["severity"] == "ERROR"
    assert payload["message"] == "boom"
    assert payload["logger"] == "test"


def test_formatter_redacts_nested_sensitive_fields() -> None:
    line = _format(_make_record("ctx", context={"value": _SECRET_HEALTH_VALUE, "id": "c1"}))
    payload = json.loads(line)
    assert _SECRET_HEALTH_VALUE not in line
    # The whole 'context' key is sensitive, so it collapses to the redaction marker.
    assert payload["context"] == "[REDACTED]"


def test_configure_logging_is_idempotent() -> None:
    root = logging.getLogger()
    configure_logging(force=True)
    count = len(root.handlers)
    configure_logging()  # no force -> no-op
    assert len(root.handlers) == count == 1


def test_configured_root_handler_redacts_end_to_end() -> None:
    configure_logging(force=True)
    handler = logging.getLogger().handlers[0]
    buf = io.StringIO()
    handler.setStream(buf)  # type: ignore[attr-defined]
    try:
        logging.getLogger("pcca.test").info(
            "putting context", extra={"value": _SECRET_HEALTH_VALUE}
        )
    finally:
        handler.setStream(handler.stream)  # restore is a no-op; buf captured already
    assert _SECRET_HEALTH_VALUE not in buf.getvalue()


def test_unhandled_exception_handler_hides_body_and_returns_500(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app()
    router = APIRouter()

    @router.post("/api/boom")
    def boom(payload: dict) -> dict:  # pragma: no cover - raises before returning
        raise RuntimeError(f"leak {payload}")

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    with caplog.at_level(logging.ERROR):
        res = client.post("/api/boom", json={"value": _SECRET_HEALTH_VALUE})

    assert res.status_code == 500
    assert res.json() == {"detail": "Internal Server Error"}
    # The request body must never reach the logs via the record's own fields.
    for record in caplog.records:
        assert _SECRET_HEALTH_VALUE not in (record.getMessage())
        assert _SECRET_HEALTH_VALUE not in json.dumps(getattr(record, "__dict__", {}), default=str)
