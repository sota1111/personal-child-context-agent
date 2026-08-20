"""Persistent Action model.

Actions survive beyond a single agent run and are re-evaluated when new school
information arrives. `idempotency_key` prevents the same planned action from being
created twice; `external_resource_id` links a completed action to the external
resource it produced (calendar event / reminder / Gmail draft) — full state
transitions are owned by later issues (SOT-2742 / SOT-2743).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ActionType(StrEnum):
    """What kind of action the agent planned."""

    MEDICATION_CONFIRMATION = "medication_confirmation"
    ALLERGEN_CONFIRMATION = "allergen_confirmation"
    CALENDAR_EVENT = "calendar_event"
    REMINDER = "reminder"
    GMAIL_DRAFT = "gmail_draft"


class ActionStatus(StrEnum):
    """Lifecycle of a persistent action."""

    PENDING = "pending"
    WAITING_FOR_PARENT = "waiting_for_parent"
    WAITING_FOR_INFORMATION = "waiting_for_information"
    READY_FOR_REVIEW = "ready_for_review"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class Action:
    """A planned/tracked action, always traceable back to its reason & evidence."""

    action_id: str
    child_id: str
    type: ActionType
    status: ActionStatus = ActionStatus.PENDING
    event_id: str | None = None
    reason: str | None = None
    evidence: list[str] = field(default_factory=list)
    due_at: datetime | None = None
    # Unique key used to prevent duplicate creation of the same planned action.
    idempotency_key: str | None = None
    # Identifier of the external resource this action produced (calendar event id,
    # Gmail draft id, ...). Set once the action is actually carried out.
    external_resource_id: str | None = None
    resolution: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        # Normalise raw strings (e.g. loaded from Firestore) back to their enums.
        if not isinstance(self.type, ActionType):
            self.type = ActionType(self.type)
        if not isinstance(self.status, ActionStatus):
            self.status = ActionStatus(self.status)
