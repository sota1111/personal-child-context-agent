"""Flow endpoints (SOT-2794): process a document, re-evaluate pending actions.

These transport the deterministic Agent Flow over HTTP. They add no judgement of
their own: ``documents:process`` runs Detect → Clarify → Plan → Act → Track →
Re-evaluate and returns the full evidence-backed :class:`FlowResult`; unapproved
actions are tracked but never executed. All routes require authentication.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from pcca.api.auth import get_current_user
from pcca.api.deps import get_flow
from pcca.api.schemas import ProcessDocumentRequest, ReevaluateRequest
from pcca.api.serialization import action_to_dict, flow_result_to_dict
from pcca.flow import AgentFlow

router = APIRouter()

FlowDep = Annotated[AgentFlow, Depends(get_flow)]
CurrentUser = Annotated[str, Depends(get_current_user)]


@router.post("/documents:process")
def process_document(
    request: ProcessDocumentRequest, flow: FlowDep, _owner: CurrentUser
) -> dict[str, Any]:
    """Run the full flow for one document and return the FlowResult (Evidence kept)."""

    result = flow.process_document(
        child_id=request.child_id,
        document_id=request.document_id,
        document_ref=request.document_ref,
        source=request.source,
        approvals=request.approvals,
    )
    return flow_result_to_dict(result)


@router.post("/actions:reevaluate")
def reevaluate_actions(
    request: ReevaluateRequest, flow: FlowDep, _owner: CurrentUser
) -> dict[str, Any]:
    """Re-evaluate a child's still-open actions; return only those that changed."""

    changed = flow.reevaluate_pending_actions(request.child_id)
    return {"child_id": request.child_id, "reevaluated": [action_to_dict(a) for a in changed]}
