"""Model + persistence skeleton tests."""

from __future__ import annotations

from datetime import datetime

from pcca.models import (
    Action,
    ActionStatus,
    ActionType,
    ChildContext,
    ConflictClassification,
    ContextStatus,
    SchoolInformation,
)
from pcca.persistence import InMemoryRepository


def test_context_status_values() -> None:
    assert ContextStatus.UNKNOWN.value == "unknown"
    # unknown and explicitly_absent are distinct concepts.
    assert ContextStatus.UNKNOWN is not ContextStatus.EXPLICITLY_ABSENT


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
