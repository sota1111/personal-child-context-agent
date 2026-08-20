"""Repository CRUD + idempotency tests, run against both backends.

The same suite runs against :class:`InMemoryRepository` and against
:class:`FirestoreRepository` wired to an in-memory fake Firestore client, so the two
backends are guaranteed to share identical semantics.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from pcca.models import (
    Action,
    ActionStatus,
    ActionType,
    ChildContext,
    ContextStatus,
    SchoolInformation,
)
from pcca.persistence import FirestoreRepository, InMemoryRepository, Repository
from tests.fakes import FakeFirestoreClient


@pytest.fixture(params=["memory", "firestore"])
def repo(request: pytest.FixtureRequest) -> Repository:
    if request.param == "memory":
        return InMemoryRepository()
    return FirestoreRepository(FakeFirestoreClient())


def _action(**overrides: object) -> Action:
    base: dict[str, object] = {
        "action_id": "act-1",
        "child_id": "child-a",
        "type": ActionType.MEDICATION_CONFIRMATION,
        "status": ActionStatus.PENDING,
        "reason": "Field trip overlaps medication time.",
    }
    base.update(overrides)
    return Action(**base)  # type: ignore[arg-type]


def test_child_context_roundtrip_and_isolation(repo: Repository) -> None:
    ctx = ChildContext(
        child_id="child-a",
        context_type="food_allergy",
        status=ContextStatus.KNOWN_PRESENT,
        value="peanut",
        last_confirmed_at=datetime(2026, 8, 1, 12, 0),
        metadata={"severity": "high"},
    )
    repo.upsert_child_context(ctx)

    got = repo.list_child_context("child-a")
    assert len(got) == 1
    assert got[0].value == "peanut"
    assert got[0].status is ContextStatus.KNOWN_PRESENT  # enum survives round-trip
    assert got[0].last_confirmed_at == datetime(2026, 8, 1, 12, 0)
    assert got[0].metadata == {"severity": "high"}
    # Isolation between children.
    assert repo.list_child_context("child-b") == []


def test_child_context_upsert_is_one_per_type(repo: Repository) -> None:
    repo.upsert_child_context(
        ChildContext(child_id="c", context_type="food_allergy", status=ContextStatus.UNKNOWN)
    )
    repo.upsert_child_context(
        ChildContext(
            child_id="c",
            context_type="food_allergy",
            status=ContextStatus.KNOWN_PRESENT,
            value="egg",
        )
    )
    got = repo.list_child_context("c")
    assert len(got) == 1
    assert got[0].status is ContextStatus.KNOWN_PRESENT
    assert got[0].value == "egg"


def test_school_information_roundtrip(repo: Repository) -> None:
    repo.upsert_school_information(
        SchoolInformation(
            document_id="doc-1",
            structured_information={"event": "Zoo Field Trip", "date": "2026-09-01"},
            evidence=["page 1: Zoo Field Trip on Sep 1"],
            source="newsletter.pdf",
        )
    )
    got = repo.get_school_information("doc-1")
    assert got is not None
    assert got.structured_information["event"] == "Zoo Field Trip"
    assert got.evidence == ["page 1: Zoo Field Trip on Sep 1"]
    assert repo.get_school_information("missing") is None


def test_action_roundtrip_preserves_enums_and_ids(repo: Repository) -> None:
    repo.upsert_action(
        _action(
            type=ActionType.CALENDAR_EVENT,
            status=ActionStatus.READY_FOR_REVIEW,
            idempotency_key="child-a:calendar_event:evt-9",
            external_resource_id="gcal-abc123",
            evidence=["school says field trip", "context says medication at noon"],
        )
    )
    got = repo.get_action("act-1")
    assert got is not None
    assert got.type is ActionType.CALENDAR_EVENT
    assert got.status is ActionStatus.READY_FOR_REVIEW
    assert got.idempotency_key == "child-a:calendar_event:evt-9"
    assert got.external_resource_id == "gcal-abc123"
    assert len(repo.list_actions("child-a")) == 1
    assert repo.get_action("missing") is None


def test_create_action_is_idempotent_on_key(repo: Repository) -> None:
    first = repo.create_action(_action(action_id="act-1", idempotency_key="dup-key"))
    # Same idempotency key, different action_id -> must NOT create a duplicate.
    second = repo.create_action(_action(action_id="act-2", idempotency_key="dup-key"))

    assert first.action_id == "act-1"
    assert second.action_id == "act-1"  # returned the existing one
    assert len(repo.list_actions("child-a")) == 1
    assert repo.get_action("act-2") is None
    assert repo.get_action_by_idempotency_key("dup-key").action_id == "act-1"


def test_create_action_without_key_always_writes(repo: Repository) -> None:
    repo.create_action(_action(action_id="act-1", idempotency_key=None))
    repo.create_action(_action(action_id="act-2", idempotency_key=None))
    assert len(repo.list_actions("child-a")) == 2


def test_get_action_by_idempotency_key_missing(repo: Repository) -> None:
    assert repo.get_action_by_idempotency_key("nope") is None
