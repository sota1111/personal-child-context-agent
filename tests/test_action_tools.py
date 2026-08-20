"""Action Tools tests (SOT-2742).

Covers the acceptance criteria for Calendar / Reminder / Gmail Draft tools:
  * all three execute (touch the outside world) ONLY after human approval,
  * Calendar duplicate registration is prevented,
  * Gmail is draft-only and never auto-sends,
  * external_resource_id / idempotency prevents duplicate execution,
  * executor failures are handled (no crash, action marked FAILED),
  * invalid requests are rejected without any side effect.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from pcca.models import ActionStatus, ActionType
from pcca.persistence import InMemoryRepository
from pcca.tools import create_calendar_event, create_gmail_draft, create_reminder
from pcca.tools.action_tools import (
    STATUS_CREATED,
    STATUS_DUPLICATE,
    STATUS_FAILED,
    STATUS_INVALID_REQUEST,
    STATUS_PENDING_APPROVAL,
    CalendarEventRequest,
    GmailDraftRequest,
    ReminderRequest,
)


class SpyExecutor:
    """Records every executor call and lets a test force a failure."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calendar_calls: list[CalendarEventRequest] = []
        self.reminder_calls: list[ReminderRequest] = []
        self.gmail_calls: list[GmailDraftRequest] = []

    @property
    def total_calls(self) -> int:
        return len(self.calendar_calls) + len(self.reminder_calls) + len(self.gmail_calls)

    def create_calendar_event(self, request: CalendarEventRequest) -> str:
        self.calendar_calls.append(request)
        if self.fail:
            raise RuntimeError("calendar backend down")
        return f"ext-cal-{len(self.calendar_calls)}"

    def create_reminder(self, request: ReminderRequest) -> str:
        self.reminder_calls.append(request)
        if self.fail:
            raise RuntimeError("reminder backend down")
        return f"ext-rem-{len(self.reminder_calls)}"

    def create_gmail_draft(self, request: GmailDraftRequest) -> str:
        self.gmail_calls.append(request)
        if self.fail:
            raise RuntimeError("gmail backend down")
        return f"ext-draft-{len(self.gmail_calls)}"


@pytest.fixture
def repo() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.fixture
def spy() -> SpyExecutor:
    return SpyExecutor()


NOW = datetime(2026, 9, 1, 12, 0, 0)


# --- Approval gate: no external effect without approval ----------------------------


def test_calendar_not_approved_does_not_touch_executor(repo, spy) -> None:
    result = create_calendar_event(
        "child-a", "Zoo Field Trip", "2026-09-18T10:30", "2026-09-18T14:30",
        approved=False, repository=repo, executor=spy, now=NOW,
    )
    assert result["status"] == STATUS_PENDING_APPROVAL
    assert result["external_resource_id"] is None
    assert result["approved"] is False
    # The outside world was never touched.
    assert spy.total_calls == 0
    # ...but the planned action IS tracked, awaiting the parent.
    actions = repo.list_actions("child-a")
    assert len(actions) == 1
    assert actions[0].status is ActionStatus.WAITING_FOR_PARENT
    assert actions[0].external_resource_id is None
    assert actions[0].type is ActionType.CALENDAR_EVENT


@pytest.mark.parametrize(
    "call",
    [
        lambda repo, spy: create_calendar_event(
            "child-a", "Zoo Trip", "2026-09-18T10:30", "2026-09-18T14:30",
            approved=False, repository=repo, executor=spy,
        ),
        lambda repo, spy: create_reminder(
            "child-a", "Confirm medication arrangements", "2026-09-17T09:00",
            approved=False, repository=repo, executor=spy,
        ),
        lambda repo, spy: create_gmail_draft(
            "child-a", "Field trip question", "Does the zoo lunch contain peanuts?",
            approved=False, repository=repo, executor=spy,
        ),
    ],
)
def test_all_three_tools_gated_on_approval(repo, spy, call) -> None:
    result = call(repo, spy)
    assert result["status"] == STATUS_PENDING_APPROVAL
    assert result["external_resource_id"] is None
    assert spy.total_calls == 0


# --- Approved path: executes exactly once -----------------------------------------


def test_calendar_approved_executes_and_records(repo, spy) -> None:
    result = create_calendar_event(
        "child-a", "Zoo Field Trip", "2026-09-18T10:30", "2026-09-18T14:30",
        approved=True, repository=repo, executor=spy, now=NOW,
    )
    assert result["status"] == STATUS_CREATED
    assert result["external_resource_id"] == "ext-cal-1"
    assert len(spy.calendar_calls) == 1

    actions = repo.list_actions("child-a")
    assert len(actions) == 1
    stored = actions[0]
    assert stored.status is ActionStatus.COMPLETED
    assert stored.external_resource_id == "ext-cal-1"
    assert stored.event_id == "ext-cal-1"
    assert stored.updated_at == NOW


def test_reminder_approved_executes(repo, spy) -> None:
    result = create_reminder(
        "child-a", "Confirm lunch allergen information", "2026-09-17T09:00",
        approved=True, repository=repo, executor=spy, now=NOW,
    )
    assert result["status"] == STATUS_CREATED
    assert result["external_resource_id"] == "ext-rem-1"
    assert len(spy.reminder_calls) == 1
    stored = repo.list_actions("child-a")[0]
    assert stored.type is ActionType.REMINDER
    assert stored.status is ActionStatus.COMPLETED
    # ISO due_at is parsed onto the Action for downstream tracking.
    assert stored.due_at == datetime(2026, 9, 17, 9, 0, 0)


# --- Calendar duplicate prevention ------------------------------------------------


def test_calendar_duplicate_registration_prevented(repo, spy) -> None:
    args = ("child-a", "Zoo Field Trip", "2026-09-18T10:30", "2026-09-18T14:30")
    first = create_calendar_event(*args, approved=True, repository=repo, executor=spy)
    second = create_calendar_event(*args, approved=True, repository=repo, executor=spy)

    assert first["status"] == STATUS_CREATED
    assert second["status"] == STATUS_DUPLICATE
    # The external calendar was hit exactly once.
    assert len(spy.calendar_calls) == 1
    # Same resource returned; only one action persisted.
    assert second["external_resource_id"] == first["external_resource_id"]
    assert len(repo.list_actions("child-a")) == 1


def test_pending_then_approved_reuses_same_action_and_executes_once(repo, spy) -> None:
    args = ("child-a", "Zoo Field Trip", "2026-09-18T10:30", "2026-09-18T14:30")
    pending = create_calendar_event(*args, approved=False, repository=repo, executor=spy)
    approved = create_calendar_event(*args, approved=True, repository=repo, executor=spy)

    assert pending["status"] == STATUS_PENDING_APPROVAL
    assert approved["status"] == STATUS_CREATED
    # Same underlying action id across the approval transition.
    assert pending["action_id"] == approved["action_id"]
    assert len(spy.calendar_calls) == 1
    assert len(repo.list_actions("child-a")) == 1


def test_explicit_idempotency_key_dedupes_across_tools_intent(repo, spy) -> None:
    key = "conflict-42-calendar"
    create_calendar_event(
        "child-a", "Zoo Field Trip", "2026-09-18T10:30", "2026-09-18T14:30",
        approved=True, repository=repo, executor=spy, idempotency_key=key,
    )
    # Different wording but the SAME explicit key -> not executed again.
    second = create_calendar_event(
        "child-a", "Zoo Trip (rescheduled title)", "2026-09-18T10:30", "2026-09-18T14:30",
        approved=True, repository=repo, executor=spy, idempotency_key=key,
    )
    assert second["status"] == STATUS_DUPLICATE
    assert len(spy.calendar_calls) == 1


def test_default_key_normalizes_whitespace_and_case(repo, spy) -> None:
    create_calendar_event(
        "child-a", "Zoo Field Trip", "2026-09-18T10:30", "2026-09-18T14:30",
        approved=True, repository=repo, executor=spy,
    )
    dup = create_calendar_event(
        "child-a", "  zoo   field trip ", "2026-09-18T10:30", "2026-09-18T14:30",
        approved=True, repository=repo, executor=spy,
    )
    assert dup["status"] == STATUS_DUPLICATE
    assert len(spy.calendar_calls) == 1


# --- Gmail draft-only --------------------------------------------------------------


def test_gmail_draft_only_never_sends(repo, spy) -> None:
    result = create_gmail_draft(
        "child-a", "Field trip lunch question",
        "Could you confirm whether the shared snacks contain peanuts?",
        approved=True, repository=repo, executor=spy, now=NOW,
    )
    assert result["status"] == STATUS_CREATED
    assert result["sent"] is False
    assert result["external_resource_id"] == "ext-draft-1"
    assert len(spy.gmail_calls) == 1
    stored = repo.list_actions("child-a")[0]
    assert stored.type is ActionType.GMAIL_DRAFT
    # A draft is left for the parent to review & send — not marked completed/sent.
    assert stored.status is ActionStatus.READY_FOR_REVIEW


def test_module_has_no_send_capability() -> None:
    import pcca.tools.action_tools as action_tools

    lowered = [name.lower() for name in dir(action_tools)]
    assert not any("send" in name for name in lowered), (
        "Gmail is draft-only: the module must expose no send path."
    )


def test_gmail_not_approved_creates_no_draft(repo, spy) -> None:
    result = create_gmail_draft(
        "child-a", "Question", "Body", approved=False, repository=repo, executor=spy,
    )
    assert result["status"] == STATUS_PENDING_APPROVAL
    assert result["sent"] is False
    assert spy.total_calls == 0


# --- Failure handling & validation ------------------------------------------------


def test_executor_failure_marks_action_failed_without_raising(repo) -> None:
    failing = SpyExecutor(fail=True)
    result = create_calendar_event(
        "child-a", "Zoo Field Trip", "2026-09-18T10:30", "2026-09-18T14:30",
        approved=True, repository=repo, executor=failing, now=NOW,
    )
    assert result["status"] == STATUS_FAILED
    assert result["external_resource_id"] is None
    stored = repo.list_actions("child-a")[0]
    assert stored.status is ActionStatus.FAILED
    assert stored.external_resource_id is None
    assert "executor error" in (stored.resolution or "")


def test_failed_action_can_be_retried(repo) -> None:
    args = ("child-a", "Zoo Field Trip", "2026-09-18T10:30", "2026-09-18T14:30")
    failing = SpyExecutor(fail=True)
    first = create_calendar_event(*args, approved=True, repository=repo, executor=failing)
    assert first["status"] == STATUS_FAILED

    healthy = SpyExecutor()
    retry = create_calendar_event(*args, approved=True, repository=repo, executor=healthy)
    # A failed action never produced an external resource, so a retry is allowed and
    # reuses the same tracked action.
    assert retry["status"] == STATUS_CREATED
    assert retry["action_id"] == first["action_id"]
    assert len(repo.list_actions("child-a")) == 1
    assert repo.list_actions("child-a")[0].status is ActionStatus.COMPLETED


@pytest.mark.parametrize(
    "call",
    [
        lambda repo, spy: create_calendar_event(
            "child-a", "", "2026-09-18T10:30", "2026-09-18T14:30",
            approved=True, repository=repo, executor=spy,
        ),
        lambda repo, spy: create_reminder(
            "child-a", "   ", "2026-09-17T09:00", approved=True, repository=repo, executor=spy,
        ),
        lambda repo, spy: create_gmail_draft(
            "child-a", "Subject", "", approved=True, repository=repo, executor=spy,
        ),
    ],
)
def test_invalid_request_rejected_without_side_effect(repo, spy, call) -> None:
    result = call(repo, spy)
    assert result["status"] == STATUS_INVALID_REQUEST
    assert result["action_id"] is None
    assert spy.total_calls == 0
    assert repo.list_actions("child-a") == []
