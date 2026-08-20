"""Personal Child Context model.

Distinguishes three statuses; `unknown` must never be treated as
`explicitly_absent`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum


class ContextStatus(StrEnum):
    """Confidence about whether a context item applies to the child."""

    KNOWN_PRESENT = "known_present"
    EXPLICITLY_ABSENT = "explicitly_absent"
    UNKNOWN = "unknown"


def treat_as_absent(status: ContextStatus) -> bool:
    """The single decision point for "is this context a confirmed absence?".

    Returns ``True`` **only** for :data:`ContextStatus.EXPLICITLY_ABSENT`. This
    enforces the core safety invariant: ``UNKNOWN`` ("we don't know") is never
    collapsed into ``EXPLICITLY_ABSENT`` ("confirmed not present / safe"). All code
    that needs to know whether an item is absent must route through here rather than
    comparing statuses ad hoc.
    """

    return status is ContextStatus.EXPLICITLY_ABSENT


@dataclass
class ChildContext:
    """A single parent-managed fact about a child (e.g. a food allergy).

    `value` holds the parent-confirmed detail (e.g. ``"peanut"`` or ``"12:00"``).
    `last_confirmed_at` drives freshness checks in the Conflict Tool.
    """

    child_id: str
    context_type: str  # e.g. "food_allergy", "scheduled_medication", "known_trigger"
    status: ContextStatus
    value: str | None = None
    source: str | None = None
    last_confirmed_at: datetime | None = None
    updated_at: datetime | None = None
    notes: str | None = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Accept a raw string (e.g. from Firestore) and normalise to the enum so the
        # invariant helpers below always operate on a real ContextStatus.
        if not isinstance(self.status, ContextStatus):
            self.status = ContextStatus(self.status)

    @property
    def is_present(self) -> bool:
        """True only when the item is confirmed to apply to the child."""

        return self.status is ContextStatus.KNOWN_PRESENT

    @property
    def is_absent(self) -> bool:
        """True only for an explicitly-confirmed absence — never for ``unknown``."""

        return treat_as_absent(self.status)

    @property
    def is_unknown(self) -> bool:
        """True when it is not established whether the item applies to the child."""

        return self.status is ContextStatus.UNKNOWN

    def is_stale(self, now: datetime, max_age: timedelta) -> bool:
        """Freshness check driven by ``last_confirmed_at``.

        An item that was never confirmed, or confirmed longer ago than ``max_age``,
        is stale and should be re-confirmed before it is relied upon.
        """

        if self.last_confirmed_at is None:
            return True
        return (now - self.last_confirmed_at) > max_age
