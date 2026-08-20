"""Conflict Tool result types.

`NO_RELEVANT_MATCH_FOUND` explicitly does **not** mean "safe" / "no risk"; it only
means nothing relevant was found from the current evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ConflictClassification(StrEnum):
    CONFIRMED_RELEVANCE = "confirmed_relevance"
    INFORMATION_MISSING = "information_missing"
    CLARIFICATION_REQUIRED = "clarification_required"
    NO_RELEVANT_MATCH_FOUND = "no_relevant_match_found"


@dataclass
class ConflictResult:
    """Outcome of reconciling School Information with Personal Child Context.

    Every result carries both sides of the evidence so an action can be traced back
    to why it was created.
    """

    classification: ConflictClassification
    reason: str
    school_evidence: list[str] = field(default_factory=list)
    personal_context_evidence: list[str] = field(default_factory=list)
