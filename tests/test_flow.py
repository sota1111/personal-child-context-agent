"""Agent Flow orchestration tests (SOT-2743).

Everything runs offline: an in-memory repository + the mock action executor stand in
for Firestore / Google Calendar / Gmail, so the whole Detect → Clarify → Plan → Act →
Track → Re-evaluate flow — including the Zoo Field Trip Example Scenario — is
exercised end-to-end without any credentials.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from pcca.flow import AgentFlow, build_flow
from pcca.models import (
    ActionStatus,
    ChildContext,
    ContextStatus,
)
from pcca.persistence import InMemoryRepository
from pcca.tools.action_tools import MockActionExecutor

CHILD = "child-1"
NOW = datetime(2026, 9, 1, 8, 0)

# Zoo Field Trip notice: a dated event window plus a school-provided lunch.
ZOO_DOC = """\
Event: Zoo Field Trip
Date: 2026-09-18
Start: 09:00
End: 15:00
Lunch: Bento provided by the school
"""


def _flow() -> tuple[AgentFlow, InMemoryRepository]:
    repo = InMemoryRepository()
    flow = build_flow(repository=repo, executor=MockActionExecutor())
    return flow, repo


def _with_medication(repo: InMemoryRepository) -> None:
    """Child takes a scheduled medication at 12:00 (inside the trip window)."""

    repo.upsert_child_context(
        ChildContext(
            child_id=CHILD,
            context_type="scheduled_medication",
            status=ContextStatus.KNOWN_PRESENT,
            value="12:00",
            last_confirmed_at=NOW,
        )
    )


# --- Example Scenario: Medication CONFIRMED_RELEVANCE + Lunch INFORMATION_MISSING ---


def test_example_scenario_end_to_end_no_approval() -> None:
    flow, repo = _flow()
    _with_medication(repo)  # no allergy context recorded => lunch is INFORMATION_MISSING

    result = flow.process_document(
        child_id=CHILD,
        document_id="zoo-notice",
        document_ref=ZOO_DOC,
        source="newsletter",
        now=NOW,
    )

    # Detect succeeded and the document was tracked as source of truth.
    assert result.detect["status"] == "parsed"
    assert repo.get_school_information("zoo-notice") is not None

    # Clarify: the most-severe classification is the confirmed medication overlap,
    # and the missing lunch/allergen info is also surfaced.
    assert result.classification == "CONFIRMED_RELEVANCE"
    rules = {f["rule"] for f in result.findings}
    assert "medication_schedule_overlap" in rules
    assert "missing_allergen_info" in rules

    # Plan/Act/Track: a calendar event, a medication reminder, and a school enquiry
    # draft are all planned and persisted.
    types = {a.type.value for a in result.actions}
    assert {"calendar_event", "reminder", "gmail_draft"} <= types

    # Human-approval gate: nothing was executed, so no external resource exists and
    # nothing is COMPLETED.
    assert all(a.external_resource_id is None for a in result.actions)
    assert all(a.status is not ActionStatus.COMPLETED for a in result.actions)

    # The missing-info action is tracked as WAITING_FOR_INFORMATION (unknown != safe).
    waiting_info = [
        a for a in result.actions if a.status is ActionStatus.WAITING_FOR_INFORMATION
    ]
    assert len(waiting_info) == 1
    assert waiting_info[0].type.value == "gmail_draft"
    assert waiting_info[0].finding_rule == "missing_allergen_info"
    # Evidence is retained on the persisted action for traceability.
    assert waiting_info[0].evidence


def test_actions_are_persisted_in_the_repository() -> None:
    flow, repo = _flow()
    _with_medication(repo)

    flow.process_document(
        child_id=CHILD, document_id="zoo-notice", document_ref=ZOO_DOC, now=NOW
    )

    persisted = repo.list_actions(CHILD)
    assert len(persisted) == 3
    # Every persisted action links back to the document that triggered it.
    assert all(a.source_document_id == "zoo-notice" for a in persisted)


# --- Human-approval gate ----------------------------------------------------------


def test_only_approved_action_is_executed() -> None:
    flow, repo = _flow()
    _with_medication(repo)

    # First pass: learn the planned action keys.
    first = flow.process_document(
        child_id=CHILD, document_id="zoo-notice", document_ref=ZOO_DOC, now=NOW
    )
    cal = next(p for p in first.planned if p.tool == "calendar_event")

    # Second pass: approve ONLY the calendar event.
    result = flow.process_document(
        child_id=CHILD,
        document_id="zoo-notice",
        document_ref=ZOO_DOC,
        approvals={cal.key},
        now=NOW,
    )

    cal_action = result.action_by_key(cal.key)
    assert cal_action is not None
    assert cal_action.status is ActionStatus.COMPLETED
    assert cal_action.external_resource_id is not None

    # Every other action stayed un-executed (no external side effect without approval).
    others = [a for a in result.actions if a.idempotency_key != cal.key]
    assert others
    assert all(a.external_resource_id is None for a in others)


def test_gmail_action_never_auto_sends_even_when_approved() -> None:
    flow, repo = _flow()
    _with_medication(repo)

    first = flow.process_document(
        child_id=CHILD, document_id="zoo-notice", document_ref=ZOO_DOC, now=NOW
    )
    draft = next(p for p in first.planned if p.tool == "gmail_draft")

    result = flow.process_document(
        child_id=CHILD,
        document_id="zoo-notice",
        document_ref=ZOO_DOC,
        approvals={draft.key},
        now=NOW,
    )
    draft_action = result.action_by_key(draft.key)
    assert draft_action is not None
    # A draft is left for the parent to review & send — never auto-completed.
    assert draft_action.status is ActionStatus.READY_FOR_REVIEW
    assert draft_action.status is not ActionStatus.COMPLETED


# --- Re-evaluate: Pending Action + New Information ---------------------------------


def test_reevaluation_transitions_waiting_for_information() -> None:
    flow, repo = _flow()
    _with_medication(repo)

    flow.process_document(
        child_id=CHILD, document_id="zoo-notice", document_ref=ZOO_DOC, now=NOW
    )
    waiting = [
        a for a in repo.list_actions(CHILD)
        if a.status is ActionStatus.WAITING_FOR_INFORMATION
    ]
    assert len(waiting) == 1

    # New information arrives: the parent confirms the child has no food allergies.
    repo.upsert_child_context(
        ChildContext(
            child_id=CHILD,
            context_type="food_allergy",
            status=ContextStatus.EXPLICITLY_ABSENT,
            last_confirmed_at=NOW,
        )
    )

    changed = flow.reevaluate_pending_actions(CHILD, now=NOW)
    assert len(changed) == 1
    assert changed[0].status is ActionStatus.READY_FOR_REVIEW
    # The agent presents it for review; it does NOT self-complete.
    assert changed[0].status is not ActionStatus.COMPLETED
    assert changed[0].resolution


def test_new_document_input_triggers_reevaluation() -> None:
    flow, repo = _flow()
    _with_medication(repo)

    flow.process_document(
        child_id=CHILD, document_id="zoo-notice", document_ref=ZOO_DOC, now=NOW
    )

    # Parent adds the missing allergy info, then a second (unrelated) document arrives.
    repo.upsert_child_context(
        ChildContext(
            child_id=CHILD,
            context_type="food_allergy",
            status=ContextStatus.EXPLICITLY_ABSENT,
            last_confirmed_at=NOW,
        )
    )
    result = flow.process_document(
        child_id=CHILD,
        document_id="library-notice",
        document_ref="Event: Library Visit\nDate: 2026-10-01\n",
        now=NOW,
    )

    assert any(
        a.status is ActionStatus.READY_FOR_REVIEW for a in result.reevaluated
    )


def test_pending_action_stays_waiting_when_info_still_missing() -> None:
    flow, repo = _flow()
    _with_medication(repo)

    flow.process_document(
        child_id=CHILD, document_id="zoo-notice", document_ref=ZOO_DOC, now=NOW
    )
    # No new information ⇒ the missing-info action must stay put (unknown != resolved).
    changed = flow.reevaluate_pending_actions(CHILD, now=NOW)
    assert changed == []
    still = [
        a for a in repo.list_actions(CHILD)
        if a.status is ActionStatus.WAITING_FOR_INFORMATION
    ]
    assert len(still) == 1


# --- Failure handling: duplicate prevention / resumability ------------------------


def test_reprocessing_same_document_does_not_duplicate_actions() -> None:
    flow, repo = _flow()
    _with_medication(repo)

    flow.process_document(
        child_id=CHILD, document_id="zoo-notice", document_ref=ZOO_DOC, now=NOW
    )
    before = {a.action_id for a in repo.list_actions(CHILD)}

    # Simulate a re-run after an interruption: the same planned actions must dedupe.
    flow.process_document(
        child_id=CHILD, document_id="zoo-notice", document_ref=ZOO_DOC, now=NOW
    )
    after = {a.action_id for a in repo.list_actions(CHILD)}
    assert before == after
    assert len(after) == 3


def test_approved_action_is_never_executed_twice() -> None:
    flow, repo = _flow()
    _with_medication(repo)

    first = flow.process_document(
        child_id=CHILD, document_id="zoo-notice", document_ref=ZOO_DOC, now=NOW
    )
    cal = next(p for p in first.planned if p.tool == "calendar_event")

    r1 = flow.process_document(
        child_id=CHILD,
        document_id="zoo-notice",
        document_ref=ZOO_DOC,
        approvals={cal.key},
        now=NOW,
    )
    resource_1 = r1.action_by_key(cal.key).external_resource_id

    # Re-approve the same action: the idempotency guard returns the same resource and
    # does not create a second calendar event.
    r2 = flow.process_document(
        child_id=CHILD,
        document_id="zoo-notice",
        document_ref=ZOO_DOC,
        approvals={cal.key},
        now=NOW,
    )
    resource_2 = r2.action_by_key(cal.key).external_resource_id

    assert resource_1 == resource_2
    calendar_actions = [
        a for a in repo.list_actions(CHILD) if a.type.value == "calendar_event"
    ]
    assert len(calendar_actions) == 1


def test_failed_executor_marks_action_failed_not_completed() -> None:
    class BoomExecutor(MockActionExecutor):
        def create_calendar_event(self, request) -> str:  # type: ignore[override]
            raise RuntimeError("calendar down")

    repo = InMemoryRepository()
    flow = AgentFlow(repository=repo, executor=BoomExecutor())
    _with_medication(repo)

    first = flow.process_document(
        child_id=CHILD, document_id="zoo-notice", document_ref=ZOO_DOC, now=NOW
    )
    cal = next(p for p in first.planned if p.tool == "calendar_event")

    result = flow.process_document(
        child_id=CHILD,
        document_id="zoo-notice",
        document_ref=ZOO_DOC,
        approvals={cal.key},
        now=NOW,
    )
    cal_action = result.action_by_key(cal.key)
    assert cal_action.status is ActionStatus.FAILED
    assert cal_action.external_resource_id is None


# --- Detect edge: a document with no usable event window --------------------------


def test_document_without_time_window_plans_no_calendar_event() -> None:
    flow, repo = _flow()
    _with_medication(repo)

    result = flow.process_document(
        child_id=CHILD,
        document_id="vague-notice",
        document_ref="Event: Some Day\n",  # no date/time ⇒ never fabricate a window
        now=NOW,
    )
    assert all(p.tool != "calendar_event" for p in result.planned)


if __name__ == "__main__":  # pragma: no cover - convenience
    raise SystemExit(pytest.main([__file__, "-q"]))
