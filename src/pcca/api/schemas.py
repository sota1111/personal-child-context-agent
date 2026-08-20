"""Request models for the serving layer (SOT-2794).

Responses are the flow's own dataclasses serialised via :mod:`pcca.api.serialization`
(so Evidence and the exact deterministic shape are preserved); only the *inputs* need
declared request schemas, which live here.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pcca.models import ContextStatus


class ProcessDocumentRequest(BaseModel):
    """Body for ``POST /api/documents:process``.

    ``document_ref`` is the raw document text (the Document Tool also accepts a path,
    but over HTTP we pass text directly). ``approvals`` lists the idempotency keys of
    planned actions the parent has approved — anything omitted is tracked but never
    executed (the human-approval gate is preserved at the serving boundary).
    """

    child_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_ref: str = Field(min_length=1, description="Raw school document text.")
    source: str = "unknown"
    approvals: list[str] = Field(default_factory=list)


class ReevaluateRequest(BaseModel):
    """Body for ``POST /api/actions:reevaluate``."""

    child_id: str = Field(min_length=1)


class ChildContextItem(BaseModel):
    """One Personal Context fact for ``PUT /api/children/{child_id}/context``.

    ``status`` keeps the three-way distinction intact (``known_present`` /
    ``explicitly_absent`` / ``unknown``); ``unknown`` is never collapsed into an
    absence.
    """

    context_type: str = Field(min_length=1)
    status: ContextStatus
    value: str | None = None
    source: str | None = None
    notes: str | None = None
    # Days since the fact was last confirmed by the parent (drives freshness checks).
    # None ⇒ never confirmed (treated as stale).
    confirmed_days_ago: int | None = None


class PutChildContextRequest(BaseModel):
    """Body for ``PUT /api/children/{child_id}/context`` — the full context set."""

    contexts: list[ChildContextItem] = Field(default_factory=list)
