"""Real-document ingestion + Vertex extractor tests (SOT-2800).

Covers:
  * PDF text ingestion (real ``pypdf`` round-trip on a generated text PDF).
  * Image / screenshot OCR through an injectable engine, and the honest
    ``processing_failed`` when no OCR engine is configured (never guessed).
  * The Vertex/Gemini structured-extractor seam: valid verbatim output is parsed,
    while a hallucinated (non-verbatim) value, a bad schema, and invalid JSON all
    degrade to ``processing_failed``.
  * Config-flag selection of the OCR engine and structured extractor.

All paths run offline: the model call and OCR are injected fakes, and the PDF path
uses pure-python ``pypdf``.
"""

from __future__ import annotations

import json

import pytest

from pcca.config import Settings
from pcca.tools.document_tool import (
    VertexStructuredExtractor,
    build_ocr_engine,
    build_structured_extractor,
    extract_school_information,
)

# --- helpers ----------------------------------------------------------------------

NOTICE_TEXT = (
    "Event: Zoo Field Trip\n"
    "Date: 2026-09-18\n"
    "Required items: hat, water bottle, notebook\n"
    "Transportation: chartered school bus\n"
)

# A minimal PNG header so magic-byte detection treats the bytes as an image; the fake
# OCR engine ignores the payload and returns known text.
_FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"fake-image-bytes"


class _FakeOcrEngine:
    """OCR stand-in returning a fixed transcription, so ingestion is tested offline."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def image_to_text(self, data: bytes) -> str:
        self.calls += 1
        return self.text


class _FakeExtractor:
    """Structured extractor stand-in returning a fixed field map."""

    def __init__(self, mapping: dict) -> None:
        self.mapping = mapping

    def extract(self, text: str) -> dict:
        return dict(self.mapping)


def _make_text_pdf(lines: list[str]) -> bytes:
    """Build a minimal single-page PDF with an extractable text layer (ASCII only)."""

    ops = ["BT", "/F1 12 Tf", "72 760 Td", "16 TL"]
    for i, line in enumerate(lines):
        esc = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        if i:
            ops.append("T*")
        ops.append(f"({esc}) Tj")
    ops.append("ET")
    content = "\n".join(ops).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref_pos = len(out)
    size = len(objects) + 1
    out += b"xref\n0 %d\n" % size
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, xref_pos)
    return bytes(out)


# --- PDF ingestion ----------------------------------------------------------------


def test_pdf_bytes_are_extracted_and_parsed() -> None:
    pytest.importorskip("pypdf")
    pdf = _make_text_pdf(
        ["Event: Zoo Field Trip", "Date: 2026-09-18", "Transportation: school bus"]
    )
    out = extract_school_information("notice.pdf", source="pdf", content=pdf)
    assert out["status"] == "parsed", out["detail"]
    assert out["structured_information"]["event"] == "Zoo Field Trip"
    # Evidence stays a verbatim substring of the extracted text.
    for entry in out["evidence"]:
        assert entry["field"] in out["structured_information"]


def test_pdf_file_path_is_extracted(tmp_path) -> None:
    pytest.importorskip("pypdf")
    pdf = _make_text_pdf(["Event: Sports Day", "Date: 2026-10-05"])
    path = tmp_path / "notice.pdf"
    path.write_bytes(pdf)
    out = extract_school_information(str(path), source="pdf")
    assert out["status"] == "parsed", out["detail"]
    assert out["structured_information"]["event"] == "Sports Day"


# --- image / screenshot OCR -------------------------------------------------------


def test_image_ocr_pipeline_with_injected_engine() -> None:
    ocr = _FakeOcrEngine(NOTICE_TEXT)
    out = extract_school_information("shot.png", source="screenshot", content=_FAKE_PNG, ocr=ocr)
    assert out["status"] == "parsed", out["detail"]
    assert ocr.calls == 1
    si = out["structured_information"]
    assert si["event"] == "Zoo Field Trip"
    assert si["required_items"] == ["hat", "water bottle", "notebook"]
    # Evidence is a verbatim substring of the OCR'd text.
    for entry in out["evidence"]:
        assert entry["text"] in NOTICE_TEXT


def test_image_file_extension_triggers_ocr(tmp_path) -> None:
    ocr = _FakeOcrEngine(NOTICE_TEXT)
    # No image magic bytes — detection must fall back to the .png extension.
    path = tmp_path / "shot.png"
    path.write_bytes(b"not-a-real-image-just-bytes")
    out = extract_school_information(str(path), source="screenshot", ocr=ocr)
    assert out["status"] == "parsed", out["detail"]
    assert ocr.calls == 1


def test_image_without_ocr_engine_is_processing_failed() -> None:
    # Default config has no OCR engine → image input is reported, never guessed.
    out = extract_school_information("shot.png", source="screenshot", content=_FAKE_PNG)
    assert out["status"] == "processing_failed"
    assert out["structured_information"] == {}
    assert "OCR engine" in out["detail"]


# --- Vertex / Gemini structured extractor -----------------------------------------


def test_vertex_extractor_valid_output_is_parsed() -> None:
    text = "Please note the outing to the Zoo on 2026-09-18. Bring a hat."

    def generate(prompt: str) -> str:
        assert "Zoo" in prompt  # the document text is embedded in the prompt
        return json.dumps({"event": "Zoo", "date": "2026-09-18", "required_items": ["hat"]})

    out = extract_school_information(
        text, source="email", extractor=VertexStructuredExtractor(generate)
    )
    assert out["status"] == "parsed", out["detail"]
    si = out["structured_information"]
    assert si == {"event": "Zoo", "date": "2026-09-18", "required_items": ["hat"]}
    # Every extracted value is retained as verbatim evidence.
    for entry in out["evidence"]:
        assert entry["text"] in text


def test_vertex_extractor_hallucinated_value_is_rejected() -> None:
    text = "The outing is on 2026-09-18."
    # 'Aquarium' never appears in the document → hallucination → processing_failed.
    generate = lambda _prompt: json.dumps({"event": "Aquarium"})  # noqa: E731
    out = extract_school_information(
        text, source="email", extractor=VertexStructuredExtractor(generate)
    )
    assert out["status"] == "processing_failed"
    assert out["structured_information"] == {}
    assert "non-verbatim" in out["detail"]


def test_vertex_extractor_bad_schema_is_rejected() -> None:
    text = "Zoo trip. Colour: blue."
    # 'colour' is not a schema field; its value is verbatim but the schema rejects it.
    generate = lambda _prompt: json.dumps({"colour": "blue"})  # noqa: E731
    out = extract_school_information(
        text, source="email", extractor=VertexStructuredExtractor(generate)
    )
    assert out["status"] == "processing_failed"
    assert "unexpected field" in out["detail"]


def test_vertex_extractor_invalid_json_is_processing_failed() -> None:
    generate = lambda _prompt: "I could not find anything useful."  # noqa: E731
    out = extract_school_information(
        "some prose", source="email", extractor=VertexStructuredExtractor(generate)
    )
    assert out["status"] == "processing_failed"
    assert out["structured_information"] == {}


def test_vertex_extractor_strips_code_fence() -> None:
    text = "Event is Sports Day."
    fenced = "```json\n" + json.dumps({"event": "Sports Day"}) + "\n```"
    out = extract_school_information(
        text, source="email", extractor=VertexStructuredExtractor(lambda _p: fenced)
    )
    assert out["status"] == "parsed", out["detail"]
    assert out["structured_information"]["event"] == "Sports Day"


def test_vertex_extractor_empty_result_is_processing_failed() -> None:
    # A document the model finds nothing in must not be guessed at.
    out = extract_school_information("prose", source="email", extractor=_FakeExtractor({}))
    assert out["status"] == "processing_failed"


# --- config-flag selection --------------------------------------------------------


def test_build_structured_extractor_default_is_deterministic() -> None:
    assert build_structured_extractor(Settings(document_extractor="deterministic")) is None
    assert build_structured_extractor(Settings(document_extractor="anything-else")) is None


def test_build_structured_extractor_selects_vertex(monkeypatch) -> None:
    sentinel = object()
    monkeypatch.setattr(
        VertexStructuredExtractor, "from_settings", classmethod(lambda cls, s: sentinel)
    )
    assert build_structured_extractor(Settings(document_extractor="vertex")) is sentinel
    assert build_structured_extractor(Settings(document_extractor="gemini")) is sentinel


def test_build_ocr_engine_selection() -> None:
    from pcca.tools.document_tool import TesseractOcrEngine, VisionOcrEngine

    assert build_ocr_engine(Settings(document_ocr="none")) is None
    assert isinstance(build_ocr_engine(Settings(document_ocr="tesseract")), TesseractOcrEngine)
    assert isinstance(build_ocr_engine(Settings(document_ocr="vision")), VisionOcrEngine)
