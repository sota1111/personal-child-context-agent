"""Action Tools — Calendar / Reminder / Gmail Draft (SOT-2742).

Turn the agent's *planned* actions into real, tracked side effects — but only with
human approval, never twice, and (for Gmail) never auto-sent.

Design (mirrors the other tools: deterministic, offline-testable, injectable):
  * **Human-approval gate.** No external side effect happens unless ``approved`` is
    True. An un-approved call still *records* the planned Action (so it is tracked
    and re-evaluated later) but never touches the outside world.
  * **Idempotency / duplicate prevention.** Every action carries an
    ``idempotency_key`` (derived deterministically from its identity when the caller
    does not supply one). The same planned action is never created twice, and an
    action that already produced an external resource is never executed again — its
    existing ``external_resource_id`` is returned instead.
  * **Gmail is draft-only.** The Gmail tool creates a *draft* and nothing else; there
    is no send path anywhere in this module. Even after approval the draft is left for
    the parent to review and send (status ``ready_for_review``).
  * **Executor seam.** The real Google Calendar / Gmail side effects are performed by
    an injected :class:`ActionExecutor`. The default :class:`MockActionExecutor` is
    fully offline (no credentials), so the approval + idempotency logic is testable
    before the external auth (SOT-2737) is wired in. A real executor implementing the
    same interface plugs in via each tool's ``executor`` argument.
  * **Failure handling.** An executor failure marks the Action ``FAILED`` and returns
    an error result; it never raises out of the tool.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from pcca.models import Action, ActionStatus, ActionType
from pcca.persistence import Repository, get_repository

# --- tool status constants (the ``status`` field of every tool's dict result) ------

STATUS_CREATED = "created"
STATUS_PENDING_APPROVAL = "pending_approval"
STATUS_DUPLICATE = "duplicate"
STATUS_INVALID_REQUEST = "invalid_request"
STATUS_FAILED = "failed"


# --- executor seam ----------------------------------------------------------------


@dataclass(frozen=True)
class CalendarEventRequest:
    """A calendar event to create in the external calendar."""

    child_id: str
    title: str
    start: str
    end: str


@dataclass(frozen=True)
class ReminderRequest:
    """A parent reminder/task to create."""

    child_id: str
    text: str
    due_at: str


@dataclass(frozen=True)
class GmailDraftRequest:
    """A Gmail **draft** to create (never sent)."""

    child_id: str
    subject: str
    body: str


class ActionExecutor(Protocol):
    """Performs the actual external side effect and returns its resource id.

    Implementations MUST raise on failure (the tool catches it and records a FAILED
    action). The Gmail method creates a **draft only** and must never send.
    """

    def create_calendar_event(self, request: CalendarEventRequest) -> str: ...

    def create_reminder(self, request: ReminderRequest) -> str: ...

    def create_gmail_draft(self, request: GmailDraftRequest) -> str: ...


class MockActionExecutor:
    """Offline, deterministic stand-in for the real Google Calendar / Gmail effects.

    Returns a stable synthetic external-resource id so runs are reproducible and no
    credentials are needed. The real executor (once SOT-2737 provides external auth)
    implements the same :class:`ActionExecutor` interface and is injected via each
    tool's ``executor`` argument.
    """

    def create_calendar_event(self, request: CalendarEventRequest) -> str:
        return _mock_id("cal", request.child_id, request.title, request.start, request.end)

    def create_reminder(self, request: ReminderRequest) -> str:
        return _mock_id("rem", request.child_id, request.text, request.due_at)

    def create_gmail_draft(self, request: GmailDraftRequest) -> str:
        # A draft id — deliberately no send path exists here or anywhere in the module.
        return _mock_id("draft", request.child_id, request.subject, request.body)


# --- public tools -----------------------------------------------------------------


def create_calendar_event(
    child_id: str,
    title: str,
    start: str,
    end: str,
    approved: bool = False,
    *,
    repository: Repository | None = None,
    executor: ActionExecutor | None = None,
    idempotency_key: str | None = None,
    reason: str | None = None,
    evidence: Sequence[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Register a school event on the calendar (only after human approval).

    Duplicate registration of the same event is prevented via the idempotency key.

    Args:
        child_id: The child the event belongs to.
        title: Event title (e.g. ``"Zoo Field Trip"``).
        start: ISO-8601 start datetime.
        end: ISO-8601 end datetime.
        approved: Whether the parent has approved creating this event. When False the
            event is recorded as awaiting approval and NOT written to the calendar.
        repository: Persistence backend (defaults to the configured one). Injectable
            for tests.
        executor: External side-effect performer (defaults to an offline mock).
        idempotency_key: Explicit dedup key; derived from the event identity if omitted.
        reason: Why this action was planned (kept with the Action for traceability).
        evidence: Evidence supporting the action.
        now: Timestamp for the created/updated Action (never fabricated when omitted).

    Returns:
        A dict with ``status`` (created / pending_approval / duplicate / invalid_request
        / failed), the ``action_id``, ``idempotency_key`` and ``external_resource_id``.
    """

    base = {"child_id": child_id, "title": title, "start": start, "end": end}
    missing = _missing(base)
    if missing:
        return _invalid(base, approved, missing)

    key = idempotency_key or _default_key(child_id, "calendar_event", title, start, end)
    request = CalendarEventRequest(child_id, title, start, end)
    return _run(
        repository=repository,
        executor=executor,
        action_type=ActionType.CALENDAR_EVENT,
        idempotency_key=key,
        executor_call=lambda ex: ex.create_calendar_event(request),
        approved=approved,
        reason=reason,
        evidence=evidence,
        due_at=_parse_iso(end),
        now=now,
        base=base,
        completed_status=ActionStatus.COMPLETED,
        set_event_id=True,
    )


def create_reminder(
    child_id: str,
    text: str,
    due_at: str,
    approved: bool = False,
    *,
    repository: Repository | None = None,
    executor: ActionExecutor | None = None,
    idempotency_key: str | None = None,
    reason: str | None = None,
    evidence: Sequence[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create a parent reminder/task derived from a conflict or missing info.

    Only executed after human approval; the same reminder is never created twice.

    Args:
        child_id: The child the reminder relates to.
        text: What the parent must do (e.g. ``"Confirm medication arrangements"``).
        due_at: ISO-8601 due datetime.
        approved: Whether the parent has approved creating this reminder.
        repository: Persistence backend (defaults to the configured one).
        executor: External side-effect performer (defaults to an offline mock).
        idempotency_key: Explicit dedup key; derived from the reminder identity if omitted.
        reason: Why this action was planned.
        evidence: Evidence supporting the action.
        now: Timestamp for the created/updated Action.

    Returns:
        A dict describing the created / pending / duplicate / invalid / failed reminder.
    """

    base = {"child_id": child_id, "text": text, "due_at": due_at}
    missing = _missing(base)
    if missing:
        return _invalid(base, approved, missing)

    key = idempotency_key or _default_key(child_id, "reminder", text, due_at)
    request = ReminderRequest(child_id, text, due_at)
    return _run(
        repository=repository,
        executor=executor,
        action_type=ActionType.REMINDER,
        idempotency_key=key,
        executor_call=lambda ex: ex.create_reminder(request),
        approved=approved,
        reason=reason,
        evidence=evidence,
        due_at=_parse_iso(due_at),
        now=now,
        base=base,
        completed_status=ActionStatus.COMPLETED,
        set_event_id=False,
    )


def create_gmail_draft(
    child_id: str,
    subject: str,
    body: str,
    approved: bool = False,
    *,
    repository: Repository | None = None,
    executor: ActionExecutor | None = None,
    idempotency_key: str | None = None,
    reason: str | None = None,
    evidence: Sequence[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create a Gmail **draft** for the parent to review — never auto-sent.

    Creating the draft is the human-in-the-loop step, so it too requires approval;
    even once created, the draft is left ``ready_for_review`` for the parent to send.
    There is no send path in this module.

    Args:
        child_id: The child the enquiry relates to.
        subject: Draft subject line.
        body: Draft body.
        approved: Whether the parent has approved creating this draft.
        repository: Persistence backend (defaults to the configured one).
        executor: External side-effect performer (defaults to an offline mock).
        idempotency_key: Explicit dedup key; derived from the draft identity if omitted.
        reason: Why this action was planned.
        evidence: Evidence supporting the action.
        now: Timestamp for the created/updated Action.

    Returns:
        A dict describing the draft. ``sent`` is always ``False`` — sending stays
        human-in-the-loop.
    """

    base: dict[str, Any] = {
        "child_id": child_id,
        "subject": subject,
        "body": body,
        "sent": False,
    }
    # Body may be empty in principle, but a meaningful enquiry needs both fields.
    missing = _missing({"child_id": child_id, "subject": subject, "body": body})
    if missing:
        return _invalid(base, approved, missing)

    key = idempotency_key or _default_key(child_id, "gmail_draft", subject, body)
    request = GmailDraftRequest(child_id, subject, body)
    return _run(
        repository=repository,
        executor=executor,
        action_type=ActionType.GMAIL_DRAFT,
        idempotency_key=key,
        executor_call=lambda ex: ex.create_gmail_draft(request),
        approved=approved,
        reason=reason,
        evidence=evidence,
        due_at=None,
        now=now,
        base=base,
        # A draft is complete only once the parent reviews & sends it themselves.
        completed_status=ActionStatus.READY_FOR_REVIEW,
        set_event_id=False,
    )


# --- shared core ------------------------------------------------------------------


def _run(
    *,
    repository: Repository | None,
    executor: ActionExecutor | None,
    action_type: ActionType,
    idempotency_key: str,
    executor_call: Callable[[ActionExecutor], str],
    approved: bool,
    reason: str | None,
    evidence: Sequence[str] | None,
    due_at: datetime | None,
    now: datetime | None,
    base: dict[str, Any],
    completed_status: ActionStatus,
    set_event_id: bool,
) -> dict[str, Any]:
    """Approval + idempotency + execution core shared by all three tools."""

    repository = repository or get_repository()
    executor = executor or MockActionExecutor()

    existing = repository.get_action_by_idempotency_key(idempotency_key)

    # Already carried out once -> never execute again (idempotency / duplicate guard).
    if existing is not None and existing.external_resource_id is not None:
        return _result(
            base,
            status=STATUS_DUPLICATE,
            approved=approved,
            action=existing,
            detail="An identical action was already carried out; not repeated.",
        )

    action_id = existing.action_id if existing is not None else _action_id(idempotency_key)

    if not approved:
        # Record the planned action as awaiting approval; do NOT touch the outside world.
        if existing is not None:
            action = existing
        else:
            action = Action(
                action_id=action_id,
                child_id=base["child_id"],
                type=action_type,
                status=ActionStatus.WAITING_FOR_PARENT,
                reason=reason,
                evidence=list(evidence or []),
                due_at=due_at,
                idempotency_key=idempotency_key,
                created_at=now,
                updated_at=now,
            )
            repository.create_action(action)
        return _result(
            base,
            status=STATUS_PENDING_APPROVAL,
            approved=False,
            action=action,
            detail="Human approval required before this action is carried out.",
        )

    # Approved and not yet executed -> perform the side effect.
    action = existing or Action(
        action_id=action_id,
        child_id=base["child_id"],
        type=action_type,
        reason=reason,
        evidence=list(evidence or []),
        due_at=due_at,
        idempotency_key=idempotency_key,
        created_at=now,
    )

    try:
        external_id = executor_call(executor)
    except Exception as exc:  # executor failure must not crash the agent
        action.status = ActionStatus.FAILED
        action.updated_at = now
        action.resolution = f"executor error: {exc}"
        repository.upsert_action(action)
        return _result(
            base,
            status=STATUS_FAILED,
            approved=True,
            action=action,
            detail=f"Action could not be carried out: {exc}",
        )

    action.status = completed_status
    action.external_resource_id = external_id
    if set_event_id:
        action.event_id = external_id
    action.updated_at = now
    repository.upsert_action(action)
    return _result(
        base,
        status=STATUS_CREATED,
        approved=True,
        action=action,
        detail="Action carried out and recorded.",
    )


# --- helpers ----------------------------------------------------------------------


def _result(
    base: dict[str, Any],
    *,
    status: str,
    approved: bool,
    action: Action,
    detail: str,
) -> dict[str, Any]:
    return {
        **base,
        "status": status,
        "approved": approved,
        "action_id": action.action_id,
        "idempotency_key": action.idempotency_key,
        "external_resource_id": action.external_resource_id,
        "action_status": action.status.value,
        "detail": detail,
    }


def _invalid(base: dict[str, Any], approved: bool, missing: list[str]) -> dict[str, Any]:
    return {
        **base,
        "status": STATUS_INVALID_REQUEST,
        "approved": approved,
        "action_id": None,
        "idempotency_key": None,
        "external_resource_id": None,
        "action_status": None,
        "detail": f"Missing required field(s): {', '.join(missing)}.",
    }


def _missing(fields: dict[str, Any]) -> list[str]:
    """Names of fields that are absent or blank (never fabricated / defaulted)."""

    return [
        name
        for name, value in fields.items()
        if not (isinstance(value, str) and value.strip())
    ]


def _normalize(part: Any) -> str:
    return " ".join(str(part).split()).casefold()


def _default_key(*parts: Any) -> str:
    """Deterministic idempotency key from an action's identity fields.

    Whitespace- and case-normalised so trivially-different wording of the *same*
    planned action still dedupes.
    """

    raw = "\x1f".join(_normalize(p) for p in parts)
    return "idem-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _action_id(key: str) -> str:
    return "act-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _mock_id(prefix: str, *parts: Any) -> str:
    raw = "\x1f".join(_normalize(p) for p in parts)
    return f"{prefix}-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _parse_iso(value: Any) -> datetime | None:
    """Parse an ISO-8601 datetime; return None when it cannot be parsed."""

    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
