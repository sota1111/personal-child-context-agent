"""Document Tool tests (SOT-2740).

Covers structured extraction of synthetic school documents, Unknown handling for
missing fields, processing-failure handling, and evidence accuracy (evidence is a
verbatim substring of the input).
"""

from __future__ import annotations

from pcca.persistence import InMemoryRepository
from pcca.tools import build_school_information, extract_school_information
from pcca.tools.document_tool import SCHEMA_FIELDS

FULL_NOTICE = """\
Field Trip Notice
Event: Zoo Field Trip
Date: 2026-09-18
Start time: 10:30
End time: 14:30
Food: Bring a bento lunch. No nuts provided by the school.
Required items: hat, water bottle, notebook
Transportation: chartered school bus
Activity: animal observation and group worksheet
Instructions: Wear comfortable shoes and arrive by 08:45.
"""


def test_extracts_all_schema_fields() -> None:
    out = extract_school_information(FULL_NOTICE, source="newsletter")
    assert out["status"] == "parsed"
    si = out["structured_information"]
    assert si["event"] == "Zoo Field Trip"
    assert si["date"] == "2026-09-18"
    assert si["start_time"] == "10:30"
    assert si["end_time"] == "14:30"
    assert si["food_information"] == "Bring a bento lunch. No nuts provided by the school."
    assert si["required_items"] == ["hat", "water bottle", "notebook"]
    assert si["transportation"] == "chartered school bus"
    assert si["activity"] == "animal observation and group worksheet"
    assert si["relevant_instructions"] == "Wear comfortable shoes and arrive by 08:45."
    # Every schema field was present -> nothing Unknown.
    assert out["unknown_fields"] == []
    assert out["source"] == "newsletter"


def test_missing_fields_are_unknown_not_guessed() -> None:
    doc = "Event: Sports Day\nDate: 2026-10-05\n"
    out = extract_school_information(doc, source="portal")
    assert out["status"] == "parsed"
    si = out["structured_information"]
    assert si == {"event": "Sports Day", "date": "2026-10-05"}
    # Absent fields are Unknown: omitted from structured_information AND flagged.
    for field in ("start_time", "food_information", "required_items", "transportation"):
        assert field not in si
        assert field in out["unknown_fields"]
    # No fabricated keys ever appear.
    assert set(si).issubset(set(SCHEMA_FIELDS))


def test_processing_failed_on_unparseable_document() -> None:
    prose = "Dear families, we hope you have a wonderful weekend ahead. Warm regards."
    out = extract_school_information(prose, source="email")
    assert out["status"] == "processing_failed"
    # Refuses to guess: no fabricated structured fields.
    assert out["structured_information"] == {}
    assert out["evidence"] == []
    assert "processing failed" in out["detail"].lower()


def test_processing_failed_on_empty_document() -> None:
    out = extract_school_information("   \n\t", source="email")
    assert out["status"] == "processing_failed"
    assert out["structured_information"] == {}


def test_evidence_is_verbatim_substring_of_input() -> None:
    out = extract_school_information(FULL_NOTICE, source="newsletter")
    assert out["evidence"], "expected evidence for a parsed document"
    for entry in out["evidence"]:
        assert entry["field"] in SCHEMA_FIELDS
        # Evidence Accuracy: the retained text must appear verbatim in the input.
        assert entry["text"] in FULL_NOTICE
    # There is evidence for exactly the fields that were extracted.
    evidence_fields = {e["field"] for e in out["evidence"]}
    assert evidence_fields == set(out["structured_information"])


def test_japanese_labels_are_supported() -> None:
    doc = "行事: 遠足\n日付: 2026-09-18\n持ち物: 帽子、水筒\n注意事項: 動きやすい服装で。\n"
    out = extract_school_information(doc, source="newsletter")
    assert out["status"] == "parsed"
    si = out["structured_information"]
    assert si["event"] == "遠足"
    assert si["date"] == "2026-09-18"
    assert si["required_items"] == ["帽子", "水筒"]
    assert si["relevant_instructions"] == "動きやすい服装で。"


def test_reads_from_file_path(tmp_path) -> None:
    path = tmp_path / "notice.txt"
    path.write_text(FULL_NOTICE, encoding="utf-8")
    out = extract_school_information(str(path), source="pdf")
    assert out["status"] == "parsed"
    assert out["structured_information"]["event"] == "Zoo Field Trip"


def test_empty_label_value_is_not_recorded() -> None:
    # A label with no value must not create a fabricated (empty) field.
    doc = "Event: Zoo Trip\nTransportation:\n"
    out = extract_school_information(doc, source="portal")
    assert out["structured_information"] == {"event": "Zoo Trip"}
    assert "transportation" in out["unknown_fields"]


def test_build_school_information_persists_via_repository() -> None:
    out = extract_school_information(FULL_NOTICE, source="newsletter")
    info = build_school_information("doc-zoo", out)
    assert info.source == "newsletter"
    # Model evidence is the flattened verbatim snippets.
    assert all(text in FULL_NOTICE for text in info.evidence)

    repo = InMemoryRepository()
    repo.upsert_school_information(info)
    stored = repo.get_school_information("doc-zoo")
    assert stored is not None
    assert stored.structured_information["event"] == "Zoo Field Trip"
