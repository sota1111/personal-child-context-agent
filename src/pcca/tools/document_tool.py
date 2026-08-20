"""Document Tool — school document -> structured School Information.

Implements SOT-2740: structured extraction from synthetic school documents
(newsletters, field-trip notices, lunch / schedule notes, plain text) into the
Structured School Information schema, with evidence retention and Unknown /
processing-failure handling.

Contract this implementation honours:
  * **Never fabricate missing values.** A field the document does not state is left
    Unknown — omitted from ``structured_information`` and listed in
    ``unknown_fields``. We never guess a value.
  * **Stop, don't guess, on parse failure.** A document we cannot extract anything
    from is reported as ``processing_failed`` rather than continuing to guess.
  * **Evidence + source are always retained.** Every extracted field carries an
    ``evidence`` entry whose text is a *verbatim substring of the input*, plus the
    document ``source`` reference.
  * **Structured output is validated.** Any output that does not match the schema
    (unexpected key / wrong type) is rejected as ``processing_failed`` — an invalid
    structured output is never surfaced as if it were a clean parse.

Extraction is deterministic (label-based) so it runs offline in CI without any
model credentials — matching the project's "prefer deterministic over LLM" rule and
its synthetic-data-driven MVP. A Gemini/Vertex extractor can later populate the same
schema behind a config flag; its output would flow through :func:`_validate_output`
exactly like this deterministic path, so the invalid-output handling already covers
it.
"""

from __future__ import annotations

import os
from typing import Any

from pcca.models import SchoolInformation

# --- Structured School Information schema -----------------------------------------

# Single-valued fields, in canonical order.
SCALAR_FIELDS: tuple[str, ...] = (
    "event",
    "date",
    "start_time",
    "end_time",
    "food_information",
    "transportation",
    "activity",
    "relevant_instructions",
)
# Multi-valued fields (extracted as ``list[str]``).
LIST_FIELDS: tuple[str, ...] = ("required_items",)
SCHEMA_FIELDS: tuple[str, ...] = SCALAR_FIELDS + LIST_FIELDS

# Return-status constants.
STATUS_PARSED = "parsed"
STATUS_PROCESSING_FAILED = "processing_failed"

# Label synonyms -> canonical field. A line is matched by the text before its first
# ':' / '：' (case-insensitively, after stripping bullet markers). English and
# Japanese synonyms are supported because the synthetic documents mirror real school
# newsletters. Keep labels specific enough that they only match an intended line.
_LABELS: dict[str, str] = {
    # event
    "event": "event",
    "title": "event",
    "subject": "event",
    "行事": "event",
    "イベント": "event",
    "行事名": "event",
    # date
    "date": "date",
    "day": "date",
    "日付": "date",
    "実施日": "date",
    "開催日": "date",
    # start_time
    "start time": "start_time",
    "start": "start_time",
    "from": "start_time",
    "開始時刻": "start_time",
    "開始": "start_time",
    # end_time
    "end time": "end_time",
    "end": "end_time",
    "until": "end_time",
    "終了時刻": "end_time",
    "終了": "end_time",
    # food_information
    "food information": "food_information",
    "food": "food_information",
    "lunch": "food_information",
    "meal": "food_information",
    "給食": "food_information",
    "食事": "food_information",
    "お弁当": "food_information",
    # required_items
    "required items": "required_items",
    "items to bring": "required_items",
    "bring": "required_items",
    "items": "required_items",
    "持ち物": "required_items",
    "必要なもの": "required_items",
    # transportation
    "transportation": "transportation",
    "transportation method": "transportation",
    "transport": "transportation",
    "travel": "transportation",
    "交通": "transportation",
    "交通手段": "transportation",
    # activity
    "activity": "activity",
    "activities": "activity",
    "活動": "activity",
    "活動内容": "activity",
    # relevant_instructions
    "relevant instructions": "relevant_instructions",
    "instructions": "relevant_instructions",
    "instruction": "relevant_instructions",
    "notes": "relevant_instructions",
    "note": "relevant_instructions",
    "注意事項": "relevant_instructions",
    "注意": "relevant_instructions",
    "連絡事項": "relevant_instructions",
}

_LABEL_SEPARATORS = (":", "：")
_ITEM_SEPARATORS = (",", "、", ";", "・")
_BULLET_PREFIX = " \t-*•・0123456789.)（）"


def extract_school_information(document_ref: str, source: str = "unknown") -> dict[str, Any]:
    """Extract structured school information from a document.

    Args:
        document_ref: The document to parse — either raw document text, or a path to
            a readable UTF-8 text file (its contents are loaded).
        source: Where the document came from (e.g. ``"email"``, ``"pdf"``,
            ``"portal"``). Retained verbatim in the output as the source reference.

    Returns:
        A dict with:
          * ``status`` — ``"parsed"`` or ``"processing_failed"``.
          * ``structured_information`` — only the fields actually found; missing
            fields are omitted (Unknown), never guessed.
          * ``unknown_fields`` — schema fields that were not present in the document.
          * ``evidence`` — one ``{"field", "text"}`` entry per extracted field, where
            ``text`` is a verbatim substring of the input.
          * ``source`` / ``document_ref`` — the source reference and original ref.
          * ``detail`` — a human-readable explanation (used on failure).
    """

    text = _read_document(document_ref)
    if text is None or not text.strip():
        return _failure(document_ref, source, "Empty or unreadable document.")

    structured, evidence = _parse(text)

    if not structured:
        # Nothing recognisable — refuse to guess; report a processing failure.
        return _failure(
            document_ref,
            source,
            "No recognisable fields found; not guessing (processing failed).",
        )

    ok, reason = _validate_output(structured)
    if not ok:
        # An invalid structured output is never surfaced as a clean parse.
        return _failure(document_ref, source, f"Invalid structured output: {reason}")

    unknown_fields = [f for f in SCHEMA_FIELDS if f not in structured]
    return {
        "status": STATUS_PARSED,
        "document_ref": document_ref,
        "source": source,
        "structured_information": structured,
        "unknown_fields": unknown_fields,
        "evidence": evidence,
        "detail": "Structured extraction succeeded.",
    }


def build_school_information(document_id: str, result: dict[str, Any]) -> SchoolInformation:
    """Build a :class:`SchoolInformation` from an :func:`extract_school_information`
    result, for persistence via the repository layer.

    Only a successfully parsed result should be persisted; evidence is flattened to
    the model's ``list[str]`` shape (the verbatim source snippets).
    """

    return SchoolInformation(
        document_id=document_id,
        structured_information=dict(result.get("structured_information", {})),
        evidence=[e["text"] for e in result.get("evidence", [])],
        source=result.get("source"),
    )


# --- internals --------------------------------------------------------------------


def _read_document(document_ref: str | None) -> str | None:
    """Return the document text: read a file path if it points at one, else treat
    ``document_ref`` as raw text."""

    if document_ref is None:
        return None
    try:
        if os.path.isfile(document_ref):
            with open(document_ref, encoding="utf-8") as fh:
                return fh.read()
    except (OSError, ValueError):
        # Not a usable path (e.g. multi-line raw text) — fall through to raw text.
        pass
    return document_ref


def _split_label(line: str) -> tuple[str | None, str | None]:
    """Split a ``label: value`` line at its first ':' / '：'.

    Returns ``(label, value)`` with surrounding whitespace stripped, or
    ``(None, None)`` when the line has no separator.
    """

    positions = [line.find(sep) for sep in _LABEL_SEPARATORS if line.find(sep) != -1]
    if not positions:
        return None, None
    idx = min(positions)
    label = line[:idx].strip().strip(_BULLET_PREFIX).strip()
    value = line[idx + 1 :].strip()
    return label, value


def _coerce_items(value: str) -> list[str]:
    """Split a required-items value into a clean list."""

    parts = [value]
    for sep in _ITEM_SEPARATORS:
        parts = [p for chunk in parts for p in chunk.split(sep)]
    return [p.strip() for p in parts if p.strip()]


def _parse(text: str) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Deterministic label-based parse. Returns ``(structured, evidence)``.

    The first non-empty occurrence of each field wins; evidence for a field is the
    verbatim source line it was extracted from (a substring of ``text``).
    """

    structured: dict[str, Any] = {}
    evidence: list[dict[str, str]] = []

    for line in text.splitlines():
        label, value = _split_label(line)
        if not label or not value:
            continue
        field = _LABELS.get(label.lower())
        if field is None or field in structured:
            continue

        if field in LIST_FIELDS:
            items = _coerce_items(value)
            if not items:
                continue
            structured[field] = items
        else:
            structured[field] = value

        # Evidence is the raw line verbatim, so it is always a substring of the input.
        evidence.append({"field": field, "text": line})

    return structured, evidence


def _validate_output(structured: dict[str, Any]) -> tuple[bool, str]:
    """Validate a structured output against the schema.

    Rejects unexpected keys and wrong value types so an invalid structured output
    (e.g. from a future model-based extractor) can never masquerade as a clean parse.
    """

    for key, value in structured.items():
        if key not in SCHEMA_FIELDS:
            return False, f"unexpected field {key!r}"
        if key in LIST_FIELDS:
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                return False, f"field {key!r} must be a list of strings"
        elif not isinstance(value, str):
            return False, f"field {key!r} must be a string"
    return True, ""


def _failure(document_ref: str, source: str, detail: str) -> dict[str, Any]:
    """Build a ``processing_failed`` result with no fabricated fields."""

    return {
        "status": STATUS_PROCESSING_FAILED,
        "document_ref": document_ref,
        "source": source,
        "structured_information": {},
        "unknown_fields": list(SCHEMA_FIELDS),
        "evidence": [],
        "detail": detail,
    }
