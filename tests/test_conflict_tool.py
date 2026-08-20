"""Conflict Tool tests (SOT-2741).

Covers the deterministic reconciliation of School Information against Personal Child
Context: medication schedule overlap, explicit allergen match, missing-info, known
trigger, freshness, inter-source contradiction, the four-way classification, the
NO_MATCH != Safe invariant, evidence on both sides, and the Grounding Rules (no
ungrounded medical generalisation).
"""

from __future__ import annotations

from datetime import datetime

from pcca.models import ChildContext, ContextStatus, SchoolInformation
from pcca.persistence import InMemoryRepository
from pcca.tools import evaluate_conflict
from pcca.tools.conflict_tool import evaluate

# --- fixtures ---------------------------------------------------------------------

FIELD_TRIP = SchoolInformation(
    document_id="doc-fieldtrip",
    structured_information={
        "event": "Zoo Field Trip",
        "date": "2026-09-18",
        "start_time": "10:30",
        "end_time": "14:30",
        "food_information": "Bring a bento lunch. Snacks with peanut butter will be shared.",
        "required_items": ["hat", "water bottle"],
        "activity": "animal observation and a petting zoo visit",
    },
)


def _ctx(context_type: str, status: ContextStatus, value: str | None = None, **kw) -> ChildContext:
    return ChildContext(
        child_id="child-a", context_type=context_type, status=status, value=value, **kw
    )


def _classes(findings) -> set[str]:
    return {f.classification.name for f in findings}


def _rules(findings) -> set[str]:
    return {f.rule for f in findings}


# --- Rule: medication schedule overlap (the headline deterministic case) ----------


def test_medication_overlap_is_confirmed_deterministically() -> None:
    med = _ctx("scheduled_medication", ContextStatus.KNOWN_PRESENT, "12:00")
    findings = evaluate(FIELD_TRIP, [med])
    overlap = [f for f in findings if f.rule == "medication_schedule_overlap"]
    assert len(overlap) == 1
    f = overlap[0]
    assert f.classification.name == "CONFIRMED_RELEVANCE"
    # Evidence on both sides.
    assert any("start_time: 10:30" in e for e in f.school_evidence)
    assert any("end_time: 14:30" in e for e in f.school_evidence)
    assert any("scheduled_medication=12:00" in e for e in f.personal_context_evidence)


def test_medication_outside_window_no_overlap() -> None:
    med = _ctx("scheduled_medication", ContextStatus.KNOWN_PRESENT, "16:00")
    findings = evaluate(FIELD_TRIP, [med])
    assert "medication_schedule_overlap" not in _rules(findings)


def test_medication_without_event_times_is_information_missing() -> None:
    doc = SchoolInformation(
        document_id="d",
        structured_information={"event": "Sports Day", "date": "2026-10-05"},
    )
    med = _ctx("scheduled_medication", ContextStatus.KNOWN_PRESENT, "12:00")
    findings = evaluate(doc, [med])
    assert "medication_overlap_undetermined" in _rules(findings)
    assert "INFORMATION_MISSING" in _classes(findings)


def test_boundary_medication_time_is_inclusive() -> None:
    med = _ctx("scheduled_medication", ContextStatus.KNOWN_PRESENT, "14:30")
    findings = evaluate(FIELD_TRIP, [med])
    assert "medication_schedule_overlap" in _rules(findings)


# --- Rule: explicit allergen match ------------------------------------------------


def test_explicit_allergen_match_is_confirmed() -> None:
    allergy = _ctx("food_allergy", ContextStatus.KNOWN_PRESENT, "peanut")
    findings = evaluate(FIELD_TRIP, [allergy])
    match = [f for f in findings if f.rule == "explicit_allergen_match"]
    assert len(match) == 1
    assert match[0].classification.name == "CONFIRMED_RELEVANCE"
    assert any("food_allergy=peanut" in e for e in match[0].personal_context_evidence)


def test_allergen_not_mentioned_is_information_missing_not_safe() -> None:
    # Egg allergy, but the food text never confirms full ingredients -> cannot rule out.
    allergy = _ctx("food_allergy", ContextStatus.KNOWN_PRESENT, "egg")
    findings = evaluate(FIELD_TRIP, [allergy])
    assert "allergen_ingredients_unconfirmed" in _rules(findings)
    assert "INFORMATION_MISSING" in _classes(findings)
    # Never a plain no-match (which would read as safe).
    assert "no_relevant_match" not in _rules(findings)


def test_negated_allergen_is_not_confirmed() -> None:
    doc = SchoolInformation(
        document_id="d",
        structured_information={
            "event": "Class Party",
            "food_information": "Snacks are peanut-free. No peanuts will be served.",
        },
    )
    allergy = _ctx("food_allergy", ContextStatus.KNOWN_PRESENT, "peanut")
    findings = evaluate(doc, [allergy])
    assert "explicit_allergen_match" not in _rules(findings)


def test_ascii_allergen_word_boundary_no_false_positive() -> None:
    # "nut" must not match inside "minute" / "peanut butter" tokens spuriously.
    doc = SchoolInformation(
        document_id="d",
        structured_information={
            "event": "Craft",
            "food_information": "Activity lasts ninety minutes; bring water.",
        },
    )
    allergy = _ctx("food_allergy", ContextStatus.KNOWN_PRESENT, "nut")
    findings = evaluate(doc, [allergy])
    assert "explicit_allergen_match" not in _rules(findings)


def test_food_event_no_allergy_info_is_information_missing() -> None:
    # Child has context (a medication) but no allergy record -> allergen unknown.
    med = _ctx("scheduled_medication", ContextStatus.EXPLICITLY_ABSENT)
    findings = evaluate(FIELD_TRIP, [med])
    assert "missing_allergen_info" in _rules(findings)
    assert "INFORMATION_MISSING" in _classes(findings)


def test_explicitly_absent_allergy_does_not_flag_missing_info() -> None:
    absent = _ctx("food_allergy", ContextStatus.EXPLICITLY_ABSENT)
    findings = evaluate(FIELD_TRIP, [absent])
    assert "missing_allergen_info" not in _rules(findings)
    assert "allergen_ingredients_unconfirmed" not in _rules(findings)


def test_unknown_allergy_status_is_not_treated_as_safe() -> None:
    unknown = _ctx("food_allergy", ContextStatus.UNKNOWN)
    findings = evaluate(FIELD_TRIP, [unknown])
    # unknown must not collapse to explicitly-absent -> still missing info.
    assert "missing_allergen_info" in _rules(findings)


# --- Rule: known trigger + Grounding Rules ----------------------------------------


def test_explicit_known_trigger_is_confirmed() -> None:
    trigger = _ctx("known_trigger", ContextStatus.KNOWN_PRESENT, "petting zoo")
    findings = evaluate(FIELD_TRIP, [trigger])
    match = [f for f in findings if f.rule == "known_trigger_match"]
    assert len(match) == 1
    assert match[0].classification.name == "CONFIRMED_RELEVANCE"


def test_grounding_no_generalisation_from_condition_alone() -> None:
    # Asthma is a medical condition, NOT an explicit trigger. A petting-zoo activity
    # must NOT be flagged from general knowledge.
    asthma = _ctx("medical_condition", ContextStatus.KNOWN_PRESENT, "asthma")
    findings = evaluate(FIELD_TRIP, [asthma])
    assert "known_trigger_match" not in _rules(findings)
    assert "CONFIRMED_RELEVANCE" not in _classes(findings)


# --- Rule: freshness --------------------------------------------------------------


def test_stale_relevant_context_requires_clarification() -> None:
    old = datetime(2026, 1, 1)
    now = datetime(2026, 8, 20)  # > 180 days later
    med = _ctx("scheduled_medication", ContextStatus.KNOWN_PRESENT, "12:00", last_confirmed_at=old)
    findings = evaluate(FIELD_TRIP, [med], now=now)
    assert "stale_personal_context" in _rules(findings)
    assert "CLARIFICATION_REQUIRED" in _classes(findings)
    # The confirmed relevance is still reported alongside.
    assert "medication_schedule_overlap" in _rules(findings)


def test_fresh_context_no_clarification() -> None:
    recent = datetime(2026, 8, 1)
    now = datetime(2026, 8, 20)
    med = _ctx(
        "scheduled_medication", ContextStatus.KNOWN_PRESENT, "12:00", last_confirmed_at=recent
    )
    findings = evaluate(FIELD_TRIP, [med], now=now)
    assert "stale_personal_context" not in _rules(findings)


def test_freshness_not_evaluated_without_now() -> None:
    old = datetime(2026, 1, 1)
    med = _ctx("scheduled_medication", ContextStatus.KNOWN_PRESENT, "12:00", last_confirmed_at=old)
    findings = evaluate(FIELD_TRIP, [med])  # no `now`
    assert "stale_personal_context" not in _rules(findings)


# --- Rule: inter-source contradiction ---------------------------------------------


def test_contradictory_context_requires_clarification() -> None:
    present = _ctx("food_allergy", ContextStatus.KNOWN_PRESENT, "peanut")
    absent = _ctx("food_allergy", ContextStatus.EXPLICITLY_ABSENT)
    findings = evaluate(FIELD_TRIP, [present, absent])
    assert "source_contradiction" in _rules(findings)
    assert "CLARIFICATION_REQUIRED" in _classes(findings)


# --- Classification: no-match / missing-context / overall -------------------------


def test_no_relevant_match_is_not_safe() -> None:
    doc = SchoolInformation(
        document_id="d",
        structured_information={"event": "Library Reading", "date": "2026-09-01"},
    )
    ctx = _ctx("food_allergy", ContextStatus.EXPLICITLY_ABSENT)
    findings = evaluate(doc, [ctx])
    assert _classes(findings) == {"NO_RELEVANT_MATCH_FOUND"}
    reason = findings[0].reason.lower()
    assert "not mean safe" in reason or "not mean" in reason


def test_no_personal_context_is_information_missing() -> None:
    findings = evaluate(FIELD_TRIP, [])
    assert _rules(findings) == {"missing_personal_context"}
    assert findings[0].classification.name == "INFORMATION_MISSING"


def test_overall_prefers_confirmed_over_missing() -> None:
    # peanut allergy -> CONFIRMED; medication without a time -> would be missing, but
    # here med overlaps so CONFIRMED. Add an unrelated missing to ensure precedence.
    allergy = _ctx("food_allergy", ContextStatus.KNOWN_PRESENT, "peanut")
    findings = evaluate(FIELD_TRIP, [allergy])
    from pcca.models import most_severe

    overall = most_severe([f.classification for f in findings])
    assert overall.name == "CONFIRMED_RELEVANCE"


# --- Tool wrapper (repository-backed) ---------------------------------------------


def test_evaluate_conflict_via_repository() -> None:
    repo = InMemoryRepository()
    repo.upsert_school_information(FIELD_TRIP)
    repo.upsert_child_context(_ctx("scheduled_medication", ContextStatus.KNOWN_PRESENT, "12:00"))

    out = evaluate_conflict("child-a", FIELD_TRIP.document_id, repository=repo)
    assert out["status"] == "evaluated"
    assert out["classification"] == "CONFIRMED_RELEVANCE"
    assert out["findings"]
    # Both evidence sides are surfaced at the top level.
    assert out["school_evidence"]
    assert out["personal_context_evidence"]


def test_evaluate_conflict_missing_document() -> None:
    repo = InMemoryRepository()
    out = evaluate_conflict("child-a", "nope", repository=repo)
    assert out["status"] == "document_not_found"
    assert out["classification"] is None


def test_every_finding_carries_school_or_personal_evidence() -> None:
    repo = InMemoryRepository()
    repo.upsert_school_information(FIELD_TRIP)
    repo.upsert_child_context(_ctx("food_allergy", ContextStatus.KNOWN_PRESENT, "peanut"))
    out = evaluate_conflict("child-a", FIELD_TRIP.document_id, repository=repo)
    for f in out["findings"]:
        assert f["school_evidence"] or f["personal_context_evidence"]
        assert f["classification"] in {
            "CONFIRMED_RELEVANCE",
            "INFORMATION_MISSING",
            "CLARIFICATION_REQUIRED",
            "NO_RELEVANT_MATCH_FOUND",
        }
