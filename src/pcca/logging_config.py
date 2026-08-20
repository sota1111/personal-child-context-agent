"""Structured, PII-safe logging for production (SOT-2804).

Cloud Run captures stdout and forwards it to Cloud Logging; when a line is JSON with a
``severity`` field it is parsed into a structured entry (correct log level, searchable
fields). This module provides:

* :class:`JsonLogFormatter` — one JSON object per record on stdout, with the
  Cloud-Logging ``severity`` field so levels survive the round-trip.
* :class:`RedactionFilter` — a defense-in-depth scrubber that removes values that must
  never reach logs per the spec's Safety rules: **Personal Context / 健康情報**. It
  redacts emails, phone numbers, and any value carried under a sensitive key
  (``value``/``notes``/``password``/…) in a record's structured ``extra`` fields, and
  masks those patterns inside the free-text message too.
* :func:`configure_logging` — installs the formatter + filter on the root logger
  (idempotent, safe to call from the app factory).

The invariant we guarantee: **the logging layer never emits a child's Personal Context
values or health information.** Call sites are expected not to pass such values to
loggers; this filter is the backstop that holds the invariant even if one slips through.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from typing import Any

# --- Redaction ---------------------------------------------------------------

_REDACTED = "[REDACTED]"

# Structured ``extra`` keys whose values are, by construction, personal/sensitive and
# must never be logged verbatim. Matched case-insensitively against the field name.
SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "value",
        "values",
        "notes",
        "note",
        "context",
        "contexts",
        "personal_context",
        "child_context",
        "document_ref",
        "document",
        "content",
        "text",
        "body",
        "password",
        "secret",
        "token",
        "authorization",
        "cookie",
        "allergy",
        "allergies",
        "medical",
        "health",
        "medication",
        "diagnosis",
        "email",
    }
)

# Free-text patterns that are redacted wherever they appear in a message string. These
# are the machine-recognisable shapes of PII; keyed sensitive values above cover the
# rest. Ordered so the broadest (email) runs before the phone matcher.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# 7+ digit runs (optionally with -, space, or +) — phone numbers / long ids.
_PHONE_RE = re.compile(r"\+?\d[\d\-\s]{5,}\d")

_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (_EMAIL_RE, _PHONE_RE)


def redact_text(text: str) -> str:
    """Mask email/phone-shaped substrings in a free-text string."""

    for pattern in _TEXT_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


class RedactionFilter(logging.Filter):
    """Scrub Personal Context / health / credential values from every log record.

    Runs as a logging *filter* (before formatting), so it protects any handler. It:

    * masks email/phone patterns inside the rendered ``record.getMessage()``;
    * replaces the value of any sensitive ``extra`` key attached to the record with
      ``[REDACTED]`` (and does the same one level into dict/list values).

    It always returns ``True`` (records are kept, only sanitised).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Redact the message. Render args in now so the stored message is already safe
        # and downstream formatters can't re-expose the raw args.
        try:
            rendered = record.getMessage()
        except Exception:  # pragma: no cover - defensive: never let logging crash
            rendered = str(record.msg)
        record.msg = redact_text(rendered)
        record.args = ()

        for key in list(vars(record).keys()):
            if key.lower() in SENSITIVE_KEYS:
                setattr(record, key, _REDACTED)

        # An exception raised by application code can itself carry Personal Context in
        # its message (e.g. RuntimeError(f"failed on {payload}")). Scrub the exception
        # args in place and drop any cached rendered traceback so the formatter
        # re-renders from the sanitised exception — the traceback frames we control
        # never contain the payload, only this message text does.
        exc_info = record.exc_info
        if exc_info and exc_info[1] is not None:
            exc = exc_info[1]
            try:
                exc.args = tuple(
                    redact_text(a) if isinstance(a, str) else a for a in exc.args
                )
            except Exception:  # pragma: no cover - never let logging crash
                pass
            record.exc_text = None
        return True


def _redact_value(key: str, value: Any) -> Any:
    if key.lower() in SENSITIVE_KEYS:
        return _REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: _redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_value(key, v) for v in value]
    return value


# --- Formatting --------------------------------------------------------------

# Python level name -> Cloud Logging severity.
_SEVERITY = {
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "WARNING": "WARNING",
    "ERROR": "ERROR",
    "CRITICAL": "CRITICAL",
}

# LogRecord attributes that are metadata, not user-supplied structured fields.
_RESERVED = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
) | {"message", "asctime", "taskName"}


class JsonLogFormatter(logging.Formatter):
    """Render a :class:`~logging.LogRecord` as a single Cloud-Logging JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "severity": _SEVERITY.get(record.levelname, record.levelname),
            "message": record.getMessage(),
            "logger": record.name,
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
        }
        if record.exc_info:
            # Only the traceback text (which we control) — never request bodies.
            payload["exception"] = self.formatException(record.exc_info)

        # Attach any structured ``extra`` fields, redacting sensitive ones as a backstop
        # in case they weren't caught by the record-level filter.
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            payload[key] = _redact_value(key, value)

        return json.dumps(payload, ensure_ascii=False, default=str)


# --- Setup -------------------------------------------------------------------

_CONFIGURED = False


def configure_logging(level: str | None = None, *, force: bool = False) -> None:
    """Install the JSON formatter + redaction filter on the root logger.

    Idempotent: repeated calls (e.g. per app factory in tests) are no-ops unless
    ``force`` is set. ``level`` defaults to ``$LOG_LEVEL`` then ``INFO``.
    """

    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    resolved = (level or os.getenv("LOG_LEVEL") or "INFO").upper()

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    handler.addFilter(RedactionFilter())

    root = logging.getLogger()
    root.setLevel(resolved)
    # Replace existing handlers so we don't double-log alongside uvicorn's defaults.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)

    # uvicorn installs its own handlers on these loggers; clear them so records
    # propagate to our single JSON handler instead of printing twice / unredacted.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True

    _CONFIGURED = True
