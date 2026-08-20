"""Model + persistence skeleton tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from pcca.models import (
    Action,
    ActionStatus,
    ActionType,
    ChildContext,
    ConflictClassification,
    ContextStatus,
    SchoolInformation,
    treat_as_absent,
)
from pcca.persistence import InMemoryRepository


def test_context_status_values() -> None:
    assert ContextStatus.UNKNOWN.value == "unknown"
    # unknown and explicitly_absent are distinct concepts.
    assert ContextStatus.UNKNOWN is not ContextStatus.EXPLICITLY_ABSENT


def test_unknown_is_never_treated_as_absent() -> None:
    # The core safety invariant, enforced at a single decision point.
    assert treat_as_absent(ContextStatus.EXPLICITLY_ABSENT) is True
    assert treat_as_absent(ContextStatus.UNKNOWN) is False
    assert treat_as_absent(ContextStatus.KNOWN_PRESENT) is False


def test_child_context_status_predicates() -> None:
    unknown = ChildContext(child_id="c", context_type="food_allergy", status=ContextStatus.UNKNOWN)
    assert unknown.is_unknown is True
    assert unknown.is_absent is False  # "we don't know" is not "confirmed absent"
    assert unknown.is_present is False

    absent = ChildContext(
        child_id="c", context_type="food_allergy", status=ContextStatus.EXPLICITLY_ABSENT
    )
    assert absent.is_absent is True
    assert absent.is_unknown is False


def test_child_context_status_accepts_raw_string() -> None:
    # Values loaded from Firestore arrive as plain strings; they must coerce.
    ctx = ChildContext(child_id="c", context_type="t", status="known_present")  # type: ignore[arg-type]
    assert ctx.status is ContextStatus.KNOWN_PRESENT
    assert ctx.is_present is True


def test_child_context_freshness() -> None:
    now = datetime(2026, 8, 20, 12, 0)
    fresh = ChildContext(
        child_id="c",
        context_type="scheduled_medication",
        status=ContextStatus.KNOWN_PRESENT,
        last_confirmed_at=now - timedelta(days=1),
    )
    stale = ChildContext(
        child_id="c",
        context_type="scheduled_medication",
        status=ContextStatus.KNOWN_PRESENT,
        last_confirmed_at=now - timedelta(days=40),
    )
    never = ChildContext(
        child_id="c", context_type="scheduled_medication", status=ContextStatus.KNOWN_PRESENT
    )
    assert fresh.is_stale(now, timedelta(days=30)) is False
    assert stale.is_stale(now, timedelta(days=30)) is True
    assert never.is_stale(now, timedelta(days=30)) is True  # never confirmed => stale


def test_action_status_enum_and_string_coercion() -> None:
    assert {s.value for s in ActionStatus} == {
        "pending",
        "waiting_for_parent",
        "waiting_for_information",
        "ready_for_review",
        "completed",
        "cancelled",
        "failed",
    }
    # Values loaded from Firestore arrive as plain strings; they must coerce.
    action = Action(
        action_id="a",
        child_id="c",
        type="calendar_event",  # type: ignore[arg-type]
        status="completed",  # type: ignore[arg-type]
    )
    assert action.type is ActionType.CALENDAR_EVENT
    assert action.status is ActionStatus.COMPLETED


def test_no_match_is_not_safe_marker() -> None:
    # NO_RELEVANT_MATCH_FOUND is a real classification, not an absence of one.
    assert ConflictClassification.NO_RELEVANT_MATCH_FOUND.value == "no_relevant_match_found"


def test_in_memory_repository_child_context_roundtrip() -> None:
    repo = InMemoryRepository()
    ctx = ChildContext(
        child_id="child-a",
        context_type="food_allergy",
        status=ContextStatus.KNOWN_PRESENT,
        value="peanut",
        last_confirmed_at=datetime(2026, 8, 1, 12, 0),
    )
    repo.upsert_child_context(ctx)
    got = repo.list_child_context("child-a")
    assert len(got) == 1
    assert got[0].value == "peanut"
    assert got[0].status is ContextStatus.KNOWN_PRESENT
    # Isolation between children.
    assert repo.list_child_context("child-b") == []


def test_in_memory_repository_action_and_school_info() -> None:
    repo = InMemoryRepository()
    repo.upsert_school_information(
        SchoolInformation(document_id="doc-1", structured_information={"event": "Zoo Field Trip"})
    )
    assert repo.get_school_information("doc-1").structured_information["event"] == "Zoo Field Trip"

    action = Action(
        action_id="act-1",
        child_id="child-a",
        type=ActionType.MEDICATION_CONFIRMATION,
        status=ActionStatus.PENDING,
        reason="Field trip overlaps medication time.",
    )
    repo.upsert_action(action)
    assert repo.get_action("act-1").status is ActionStatus.PENDING
    assert len(repo.list_actions("child-a")) == 1
