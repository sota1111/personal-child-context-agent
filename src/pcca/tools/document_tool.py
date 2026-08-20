"""Document Tool — school document -> structured School Information.

Implements SOT-2740 (deterministic label extraction) and SOT-2800 (real-document
ingestion: PDF / image / screenshot -> text, plus an optional Vertex/Gemini
structured extractor behind a config flag). Both extraction paths feed the same
schema validation, evidence retention, and Unknown / processing-failure handling.

Contract this implementation honours (identical for every extraction path):
  * **Never fabricate missing values.** A field the document does not state is left
    Unknown — omitted from ``structured_information`` and listed in
    ``unknown_fields``. We never guess a value.
  * **Stop, don't guess, on parse failure.** A document we cannot extract anything
    from is reported as ``processing_failed`` rather than continuing to guess.
  * **Evidence + source are always retained.** Every extracted field carries an
    ``evidence`` entry whose text is a *verbatim substring of the input*, plus the
    document ``source`` reference. This holds for the LLM path too: an extracted
    value that is not a verbatim substring of the input is treated as a hallucination
    and rejected as ``processing_failed``.
  * **Structured output is validated.** Any output that does not match the schema
    (unexpected key / wrong type) is rejected as ``processing_failed`` — an invalid
    structured output is never surfaced as if it were a clean parse.

Ingestion (SOT-2800): raw text and ``.txt`` files are read directly; PDFs are text
extracted with ``pypdf``; images / screenshots are OCR'd through an injectable
:class:`OcrEngine` (real engines — tesseract / Cloud Vision — are lazily imported and
selected by config; tests inject a fake so CI stays offline). A scanned PDF with no
text layer falls back to OCR when an engine is available.

Extraction defaults to the deterministic (label-based) path so it runs offline in CI
without any model credentials — matching the project's "prefer deterministic over LLM"
rule and its synthetic-data-driven MVP. Setting ``PCCA_DOCUMENT_EXTRACTOR=vertex``
routes messy documents the labels cannot parse through a Gemini/Vertex extractor whose
output flows through the exact same verbatim-evidence and schema validation below.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol

from pcca.models import SchoolInformation

if TYPE_CHECKING:  # optional deps / typing only — never imported at runtime here.
    from pcca.config import Settings

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

# Magic-byte signatures for the binary document types we ingest.
_PDF_MAGIC = b"%PDF"
_IMAGE_MAGICS: tuple[bytes, ...] = (
    b"\x89PNG\r\n\x1a\n",  # PNG
    b"\xff\xd8\xff",  # JPEG
    b"GIF87a",  # GIF
    b"GIF89a",
    b"BM",  # BMP
    b"II*\x00",  # TIFF (little-endian)
    b"MM\x00*",  # TIFF (big-endian)
)
_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp")


# --- OCR engine seam (image / scanned-PDF -> text) --------------------------------


class OcrEngine(Protocol):
    """Turns raster image bytes into text.

    Implementations MUST return the recognised text (empty string when nothing is
    found). The real engines (tesseract / Cloud Vision) are lazily imported; tests
    inject a fake so the ingestion pipeline is exercised offline.
    """

    def image_to_text(self, data: bytes) -> str: ...


class TesseractOcrEngine:
    """OCR via the local Tesseract binary (``pytesseract`` + Pillow), lazily imported.

    Requires the system ``tesseract`` binary and the ``[ocr]`` optional dependencies;
    kept out of import time so the core install stays lightweight and offline.
    """

    def __init__(self, lang: str = "eng+jpn") -> None:
        self.lang = lang

    def image_to_text(self, data: bytes) -> str:
        import io

        import pytesseract
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            return str(pytesseract.image_to_string(image, lang=self.lang))


class VisionOcrEngine:
    """OCR via Google Cloud Vision ``document_text_detection`` (lazily imported).

    Uses Application Default Credentials, mirroring the rest of the project's Google
    access; only constructed when ``PCCA_DOCUMENT_OCR=vision`` selects it.
    """

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            from google.cloud import vision  # type: ignore[attr-defined]

            self._client = vision.ImageAnnotatorClient()
        return self._client

    def image_to_text(self, data: bytes) -> str:
        from google.cloud import vision  # type: ignore[attr-defined]

        client = self._get_client()
        response = client.document_text_detection(image=vision.Image(content=data))
        if getattr(response, "error", None) and response.error.message:
            raise RuntimeError(f"Cloud Vision error: {response.error.message}")
        return str(response.full_text_annotation.text)


def build_ocr_engine(settings: Settings | None = None) -> OcrEngine | None:
    """Select the OCR engine from configuration — default ``none`` (no OCR).

    ``PCCA_DOCUMENT_OCR`` = ``tesseract`` | ``vision`` selects a real engine; any other
    value (incl. the default ``none``) disables OCR, so image input without an engine
    is reported as ``processing_failed`` rather than silently dropped.
    """

    if settings is None:
        settings = _load_settings()
    choice = settings.document_ocr.strip().lower()
    if choice == "tesseract":
        return TesseractOcrEngine()
    if choice == "vision":
        return VisionOcrEngine()
    return None


# --- structured extractor seam (text -> field map) --------------------------------


class StructuredExtractor(Protocol):
    """Extracts structured fields from already-textualised document content.

    Returns a mapping of schema field -> value (``str`` scalar or ``list[str]``),
    containing ONLY the fields it is confident about. The tool then validates every
    value against the schema and confirms each is a verbatim substring of the input,
    so a hallucinated value can never be surfaced as a clean parse.
    """

    def extract(self, text: str) -> dict[str, Any]: ...


# Prompt for the Vertex/Gemini extractor. It is deliberately strict: JSON only, no
# guessing, values must be verbatim spans so the downstream verbatim check passes.
_VERTEX_PROMPT = """\
You extract structured school information from a document. Return ONLY a JSON object.

Rules:
- Keys may only be: {fields}.
- Include a key ONLY when its value is explicitly stated in the document. If a field
  is not stated, OMIT it entirely — never guess or infer a value.
- Every value MUST be copied verbatim (an exact substring) from the document text.
- "required_items" must be a JSON array of verbatim strings; every other field is a
  single string.
- Do not add commentary, code fences, or any text outside the JSON object.

Document:
<<<
{text}
>>>
"""


class VertexStructuredExtractor:
    """Gemini-via-Vertex structured extractor (SOT-2800), behind an injectable seam.

    The model call is injected as a ``generate`` callable (prompt -> raw text) so unit
    tests drive it deterministically with no credentials, mirroring the executor seam
    in ``action_tools.py``. :meth:`from_settings` wires a real ``google-genai`` Vertex
    client lazily. Output is parsed as JSON here; all schema / verbatim validation is
    done by the tool, so a malformed or hallucinated response degrades to
    ``processing_failed`` rather than a fabricated parse.
    """

    def __init__(self, generate: Callable[[str], str]) -> None:
        self._generate = generate

    @classmethod
    def from_settings(cls, settings: Settings) -> VertexStructuredExtractor:
        """Build a production extractor backed by a Vertex ``google-genai`` client."""

        from google import genai  # local import: optional Gemini/Vertex dependency

        client = genai.Client(
            vertexai=settings.use_vertexai,
            project=settings.project,
            location=settings.location,
        )
        model = settings.model

        def generate(prompt: str) -> str:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config={"temperature": 0, "response_mime_type": "application/json"},
            )
            return response.text or ""

        return cls(generate=generate)

    def extract(self, text: str) -> dict[str, Any]:
        prompt = _VERTEX_PROMPT.format(fields=", ".join(SCHEMA_FIELDS), text=text)
        raw = self._generate(prompt)
        return _parse_model_json(raw)


def _parse_model_json(raw: str) -> dict[str, Any]:
    """Parse a model response into a field map, tolerating ```json code fences.

    Raises ``ValueError`` on anything that is not a JSON object — the tool catches it
    and reports ``processing_failed`` (we never guess from an unparseable response).
    """

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # Strip a leading ```json / ``` fence and the trailing ```.
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else ""
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[: -len("```")]
    cleaned = cleaned.strip()
    if not cleaned:
        raise ValueError("empty model response")
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model response was not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("model response was not a JSON object")
    return parsed


def build_structured_extractor(settings: Settings | None = None) -> StructuredExtractor | None:
    """Select the structured extractor from configuration.

    ``PCCA_DOCUMENT_EXTRACTOR`` = ``vertex``/``gemini`` opts into the Vertex/Gemini
    extractor; any other value (incl. the default ``deterministic``) returns ``None``,
    meaning "use the built-in deterministic label parser".
    """

    if settings is None:
        settings = _load_settings()
    if settings.document_extractor.strip().lower() in {"vertex", "gemini"}:
        return VertexStructuredExtractor.from_settings(settings)
    return None


def _load_settings() -> Settings:
    from pcca.config import Settings as _Settings

    return _Settings.from_env()


# --- public entry point -----------------------------------------------------------


def extract_school_information(
    document_ref: str,
    source: str = "unknown",
    *,
    content: bytes | None = None,
    ocr: OcrEngine | None = None,
    extractor: StructuredExtractor | None = None,
) -> dict[str, Any]:
    """Extract structured school information from a document.

    Args:
        document_ref: The document to parse — raw document text, or a path to a
            readable file. Text / ``.txt`` files are read directly; ``.pdf`` files are
            text-extracted; image / screenshot files are OCR'd via ``ocr``.
        source: Where the document came from (e.g. ``"email"``, ``"pdf"``,
            ``"portal"``). Retained verbatim in the output as the source reference.
        content: Raw document bytes (PDF / image), when the caller has the bytes rather
            than a file path. Its type is detected from its magic bytes.
        ocr: OCR engine for image / scanned-PDF input. Defaults to the configured
            engine (``PCCA_DOCUMENT_OCR``); ``None`` means image input cannot be read
            and is reported as ``processing_failed`` (never guessed).
        extractor: Structured extractor for the textualised content. Defaults to the
            configured one (``PCCA_DOCUMENT_EXTRACTOR``); ``None`` uses the built-in
            deterministic label parser.

    Returns:
        A dict with:
          * ``status`` — ``"parsed"`` or ``"processing_failed"``.
          * ``structured_information`` — only the fields actually found; missing
            fields are omitted (Unknown), never guessed.
          * ``unknown_fields`` — schema fields that were not present in the document.
          * ``evidence`` — ``{"field", "text"}`` entries whose ``text`` is a verbatim
            substring of the input.
          * ``source`` / ``document_ref`` — the source reference and original ref.
          * ``detail`` — a human-readable explanation (used on failure).
    """

    text, read_error = _load_text(document_ref, content=content, ocr=ocr)
    if read_error is not None:
        return _failure(document_ref, source, read_error)
    if text is None or not text.strip():
        return _failure(document_ref, source, "Empty or unreadable document.")

    if extractor is None:
        extractor = build_structured_extractor()

    if extractor is None:
        structured, evidence = _parse(text)
    else:
        try:
            raw = extractor.extract(text)
        except Exception as exc:  # noqa: BLE001 - any extractor failure is a soft failure
            return _failure(document_ref, source, f"Extractor failed: {exc}")
        structured, evidence, verbatim_error = _verbatim_evidence(raw, text)
        if verbatim_error is not None:
            return _failure(document_ref, source, verbatim_error)

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


# --- ingestion (bytes / path -> text) ---------------------------------------------


def _load_text(
    document_ref: str | None,
    *,
    content: bytes | None,
    ocr: OcrEngine | None,
) -> tuple[str | None, str | None]:
    """Turn an input into plain text. Returns ``(text, error_detail)``.

    ``error_detail`` is non-None only for an ingestion failure we want surfaced with a
    specific reason (e.g. image input but no OCR engine). Plain-text / ``.txt`` input
    keeps the original raw-text behaviour so existing callers are unaffected.
    """

    if content is not None:
        return _text_from_bytes(content, ocr=ocr)

    if document_ref is None:
        return None, None

    try:
        is_file = os.path.isfile(document_ref)
    except (OSError, ValueError):
        is_file = False

    if is_file:
        try:
            with open(document_ref, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            return None, f"Could not read file: {exc}"
        return _text_from_bytes(data, ocr=ocr, path=document_ref)

    # Not a path — treat the argument as raw document text.
    return document_ref, None


def _text_from_bytes(
    data: bytes,
    *,
    ocr: OcrEngine | None,
    path: str | None = None,
) -> tuple[str | None, str | None]:
    """Detect the document type from ``data`` (and optional ``path`` extension) and
    return its text, resolving the OCR engine from config when needed."""

    if data.startswith(_PDF_MAGIC):
        return _pdf_to_text(data, ocr=_resolve_ocr(ocr))

    ext = os.path.splitext(path)[1].lower() if path else ""
    is_image = data.startswith(_IMAGE_MAGICS) or ext in _IMAGE_EXTENSIONS
    if is_image:
        engine = _resolve_ocr(ocr)
        if engine is None:
            return None, (
                "Image input requires an OCR engine; none configured "
                "(set PCCA_DOCUMENT_OCR=tesseract|vision or pass ocr=)."
            )
        try:
            return engine.image_to_text(data), None
        except Exception as exc:  # noqa: BLE001 - OCR failure is a soft processing failure
            return None, f"OCR failed: {exc}"

    # Fall back to decoding as UTF-8 text (plain-text file read as bytes).
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, "Unsupported binary document (not PDF, a known image, or UTF-8 text)."


def _resolve_ocr(ocr: OcrEngine | None) -> OcrEngine | None:
    """Use the caller-supplied OCR engine, else the one selected by configuration."""

    return ocr if ocr is not None else build_ocr_engine()


def _pdf_to_text(data: bytes, *, ocr: OcrEngine | None) -> tuple[str | None, str | None]:
    """Extract text from a PDF via ``pypdf``; fall back to OCR for a scanned PDF."""

    try:
        import io

        from pypdf import PdfReader
    except ImportError:
        return None, "PDF support requires the 'pypdf' dependency (install .[documents])."

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:  # noqa: BLE001 - malformed PDF is a soft processing failure
        return None, f"Could not read PDF: {exc}"

    text = "\n".join(pages).strip()
    if text:
        return text, None

    # No embedded text layer (scanned PDF) — OCR the rendered pages if we can.
    if ocr is not None:
        ocr_text, ocr_error = _ocr_pdf_pages(data, ocr)
        if ocr_error is not None:
            return None, ocr_error
        return ocr_text, None
    return None, "PDF has no extractable text layer and no OCR engine is configured."


def _ocr_pdf_pages(data: bytes, ocr: OcrEngine) -> tuple[str | None, str | None]:
    """Render PDF pages to images (``pdf2image``) and OCR them."""

    try:
        from pdf2image import convert_from_bytes
    except ImportError:
        return None, "Scanned-PDF OCR requires the 'pdf2image' dependency (install .[ocr])."

    try:
        import io

        images = convert_from_bytes(data)
        texts: list[str] = []
        for image in images:
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            texts.append(ocr.image_to_text(buffer.getvalue()))
    except Exception as exc:  # noqa: BLE001 - rendering/OCR failure is a soft failure
        return None, f"Scanned-PDF OCR failed: {exc}"
    return "\n".join(texts), None


# --- deterministic parse ----------------------------------------------------------


def _read_document(document_ref: str | None) -> str | None:
    """Return the document text for a path or raw-text argument.

    Retained for backwards compatibility (text / ``.txt`` path behaviour); the richer
    ingestion path is :func:`_load_text`.
    """

    text, _ = _load_text(document_ref, content=None, ocr=None)
    return text


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


def _verbatim_evidence(
    raw: dict[str, Any],
    text: str,
) -> tuple[dict[str, Any], list[dict[str, str]], str | None]:
    """Validate an extractor's field map and build verbatim evidence.

    Returns ``(structured, evidence, error)``. Every scalar value / list item must be a
    verbatim substring of ``text``; the first value that is not is reported as an error
    (``processing_failed``), so a hallucinated LLM value can never be surfaced. Unknown
    keys / wrong types are left for :func:`_validate_output` to reject.
    """

    structured: dict[str, Any] = {}
    evidence: list[dict[str, str]] = []

    for field, value in raw.items():
        if field in LIST_FIELDS:
            if not isinstance(value, list):
                return {}, [], f"field {field!r} must be a list of strings"
            items = [str(v) for v in value]
            for item in items:
                if item not in text:
                    return {}, [], f"non-verbatim value for {field!r}: {item!r}"
                evidence.append({"field": field, "text": item})
            if not items:
                continue
            structured[field] = items
        else:
            if not isinstance(value, str):
                return {}, [], f"field {field!r} must be a string"
            if value not in text:
                return {}, [], f"non-verbatim value for {field!r}: {value!r}"
            structured[field] = value
            evidence.append({"field": field, "text": value})

    return structured, evidence, None


def _validate_output(structured: dict[str, Any]) -> tuple[bool, str]:
    """Validate a structured output against the schema.

    Rejects unexpected keys and wrong value types so an invalid structured output
    (e.g. from a model-based extractor) can never masquerade as a clean parse.
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
