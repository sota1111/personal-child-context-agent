"""Personal Child Context model.

Distinguishes three statuses; `unknown` must never be treated as
`explicitly_absent`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ContextStatus(StrEnum):
    """Confidence about whether a context item applies to the child."""

    KNOWN_PRESENT = "known_present"
    EXPLICITLY_ABSENT = "explicitly_absent"
    UNKNOWN = "unknown"


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
