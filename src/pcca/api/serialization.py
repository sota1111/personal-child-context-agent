"""JSON serialisation for the flow's domain objects (SOT-2794).

Every serialiser is total and evidence-preserving: Actions, planned actions, contexts
and the whole :class:`~pcca.flow.FlowResult` carry their ``evidence`` and ``reason``
into the HTTP response verbatim. Enums become their string values and datetimes become
ISO-8601 strings, so the output is plain JSON with no medical judgement added.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pcca.flow import FlowResult, PlannedAction
from pcca.models import Action, ChildContext


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def action_to_dict(action: Action) -> dict[str, Any]:
    return {
        "action_id": action.action_id,
        "child_id": action.child_id,
        "type": action.type.value,
        "status": action.status.value,
        "reason": action.reason,
        "evidence": list(action.evidence),
        "due_at": _iso(action.due_at),
        "idempotency_key": action.idempotency_key,
        "external_resource_id": action.external_resource_id,
        "resolution": action.resolution,
        "source_document_id": action.source_document_id,
        "finding_rule": action.finding_rule,
        "created_at": _iso(action.created_at),
        "updated_at": _iso(action.updated_at),
    }


def planned_to_dict(planned: PlannedAction) -> dict[str, Any]:
    return {
        "key": planned.key,
        "tool": planned.tool,
        "action_type": planned.action_type.value,
        "waiting_status": planned.waiting_status.value,
        "reason": planned.reason,
        "payload": dict(planned.payload),
        "evidence": list(planned.evidence),
        "finding_rule": planned.finding_rule,
        "due_at": _iso(planned.due_at),
    }


def context_to_dict(ctx: ChildContext) -> dict[str, Any]:
    return {
        "child_id": ctx.child_id,
        "context_type": ctx.context_type,
        "status": ctx.status.value,
        "value": ctx.value,
        "source": ctx.source,
        "notes": ctx.notes,
        "last_confirmed_at": _iso(ctx.last_confirmed_at),
        "updated_at": _iso(ctx.updated_at),
    }


def flow_result_to_dict(result: FlowResult) -> dict[str, Any]:
    """Serialise a full :class:`FlowResult` — every step, with Evidence retained."""

    return {
        "child_id": result.child_id,
        "document_id": result.document_id,
        "detect": result.detect,
        "classification": result.classification,
        "findings": result.findings,
        "planned": [planned_to_dict(p) for p in result.planned],
        "actions": [action_to_dict(a) for a in result.actions],
        "reevaluated": [action_to_dict(a) for a in result.reevaluated],
    }
