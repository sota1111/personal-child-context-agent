"""Child endpoints (SOT-2794): Personal Context CRUD + tracked actions.

The Personal Context is the parent-managed source of truth the flow reconciles school
information against. These routes read/replace it and list a child's tracked actions.
The three-way status (``known_present`` / ``explicitly_absent`` / ``unknown``) is kept
exactly as sent — ``unknown`` is never turned into an absence here. All routes require
authentication.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from pcca.api.auth import get_current_user
from pcca.api.deps import get_shared_repository
from pcca.api.schemas import PutChildContextRequest
from pcca.api.serialization import action_to_dict, context_to_dict
from pcca.models import ChildContext
from pcca.persistence import Repository

router = APIRouter()

RepoDep = Annotated[Repository, Depends(get_shared_repository)]
CurrentUser = Annotated[str, Depends(get_current_user)]


@router.get("/children/{child_id}/context")
def get_child_context(child_id: str, repo: RepoDep, _owner: CurrentUser) -> dict[str, Any]:
    """Return the child's current Personal Context set."""

    contexts = repo.list_child_context(child_id)
    return {"child_id": child_id, "contexts": [context_to_dict(c) for c in contexts]}


@router.put("/children/{child_id}/context")
def put_child_context(
    child_id: str, request: PutChildContextRequest, repo: RepoDep, _owner: CurrentUser
) -> dict[str, Any]:
    """Upsert the child's Personal Context facts, preserving the three-way status.

    ``confirmed_days_ago`` is materialised into a real ``last_confirmed_at`` timestamp
    (``None`` ⇒ never confirmed / always stale), so the Conflict Tool's freshness
    checks work against the stored context.
    """

    now = datetime.now()
    stored: list[ChildContext] = []
    for item in request.contexts:
        last_confirmed = (
            None
            if item.confirmed_days_ago is None
            else now - timedelta(days=item.confirmed_days_ago)
        )
        ctx = ChildContext(
            child_id=child_id,
            context_type=item.context_type,
            status=item.status,
            value=item.value,
            source=item.source,
            notes=item.notes,
            last_confirmed_at=last_confirmed,
            updated_at=now,
        )
        repo.upsert_child_context(ctx)
        stored.append(ctx)
    return {"child_id": child_id, "contexts": [context_to_dict(c) for c in stored]}


@router.get("/children/{child_id}/actions")
def list_child_actions(child_id: str, repo: RepoDep, _owner: CurrentUser) -> dict[str, Any]:
    """List the child's tracked actions (each with its reason & evidence)."""

    actions = repo.list_actions(child_id)
    return {"child_id": child_id, "actions": [action_to_dict(a) for a in actions]}
