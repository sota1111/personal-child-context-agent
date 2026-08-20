"""Conflict Tool — reconcile School Information with Personal Child Context.

Interface stub (SOT-2738). The full deterministic ruleset (time-overlap, explicit
allergen match, missing-info, freshness, inter-document contradiction) and the LLM
fallback are implemented in SOT-2741.

Design rule: prefer **deterministic** logic over delegating everything to the LLM.
`NO_RELEVANT_MATCH_FOUND` never means "safe".
"""

from __future__ import annotations


def evaluate_conflict(child_id: str, document_id: str) -> dict:
    """Evaluate whether a school document is relevant to a specific child.

    Args:
        child_id: The child whose Personal Context to reconcile against.
        document_id: The structured School Information to evaluate.

    Returns:
        A dict with `classification` (one of CONFIRMED_RELEVANCE /
        INFORMATION_MISSING / CLARIFICATION_REQUIRED / NO_RELEVANT_MATCH_FOUND),
        `reason`, and both sides of the evidence.
    """

    return {
        "status": "not_implemented",
        "detail": "Deterministic conflict evaluation is implemented in SOT-2741.",
        "child_id": child_id,
        "document_id": document_id,
        "classification": None,
        "school_evidence": [],
        "personal_context_evidence": [],
    }
