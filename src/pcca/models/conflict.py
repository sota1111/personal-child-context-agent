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


# Severity order, most severe first. Used to pick the overall classification when a
# single evaluation produces several findings. Rationale:
#   * CONFIRMED_RELEVANCE — a concrete, deterministic risk was found; act on it.
#   * INFORMATION_MISSING — a relevant category exists but a fact needed to rule out
#     risk is unknown. Ranked above CLARIFICATION because an unknown is a potential
#     False Negative, which this tool must treat as a serious risk.
#   * CLARIFICATION_REQUIRED — the known facts are stale or mutually contradictory;
#     a human must reconcile them.
#   * NO_RELEVANT_MATCH_FOUND — nothing matched. Never an assertion of safety.
CLASSIFICATION_PRIORITY: tuple[ConflictClassification, ...] = (
    ConflictClassification.CONFIRMED_RELEVANCE,
    ConflictClassification.INFORMATION_MISSING,
    ConflictClassification.CLARIFICATION_REQUIRED,
    ConflictClassification.NO_RELEVANT_MATCH_FOUND,
)


def most_severe(
    classifications: list[ConflictClassification],
) -> ConflictClassification:
    """Return the most severe classification per :data:`CLASSIFICATION_PRIORITY`.

    Defaults to ``NO_RELEVANT_MATCH_FOUND`` for an empty list — which, per this
    module's contract, still does not mean "safe".
    """

    for level in CLASSIFICATION_PRIORITY:
        if level in classifications:
            return level
    return ConflictClassification.NO_RELEVANT_MATCH_FOUND


@dataclass
class ConflictFinding:
    """One deterministic finding from reconciling a document against one child.

    Each finding is self-contained: it names the rule that fired and carries both
    sides of the evidence so an action can be traced back to why it was created.
    """

    classification: ConflictClassification
    rule: str
    reason: str
    school_evidence: list[str] = field(default_factory=list)
    personal_context_evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        # Use the enum member *name* (e.g. "CONFIRMED_RELEVANCE") in serialized output
        # so it mirrors the classification spec the Root Agent reasons about.
        return {
            "classification": self.classification.name,
            "rule": self.rule,
            "reason": self.reason,
            "school_evidence": list(self.school_evidence),
            "personal_context_evidence": list(self.personal_context_evidence),
        }


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
