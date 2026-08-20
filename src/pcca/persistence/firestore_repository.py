"""Cloud Firestore-backed repository — the persistent source of truth (SOT-2739).

Firestore holds the durable facts and action state; ADK Session/State only ever
holds transient *workflow* state. This module maps the domain models to/from
Firestore documents and implements the storage-agnostic :class:`Repository`
protocol, so nothing else in the agent needs to know the backend.

The client is injectable (`FirestoreRepository(client=...)`) so the CRUD logic can
be exercised against a fake in tests / CI without any GCP credentials, while
production uses :meth:`from_settings` to build a real ``google.cloud.firestore``
client via Application Default Credentials.
"""

from __future__ import annotations

from typing import Any

from google.cloud.firestore_v1.base_query import FieldFilter

from pcca.config import Settings
from pcca.models import Action, ChildContext, SchoolInformation
from pcca.persistence.repository import Repository

# Collection names (the persistent source of truth).
CHILD_CONTEXT_COLLECTION = "child_context"
SCHOOL_INFORMATION_COLLECTION = "school_information"
ACTIONS_COLLECTION = "actions"


# --- Serialization: domain model <-> Firestore document ---------------------


def _child_context_to_doc(ctx: ChildContext) -> dict[str, Any]:
    return {
        "child_id": ctx.child_id,
        "context_type": ctx.context_type,
        "status": ctx.status.value,
        "value": ctx.value,
        "source": ctx.source,
        "last_confirmed_at": ctx.last_confirmed_at,
        "updated_at": ctx.updated_at,
        "notes": ctx.notes,
        "metadata": ctx.metadata,
    }


def _child_context_from_doc(doc: dict[str, Any]) -> ChildContext:
    return ChildContext(
        child_id=doc["child_id"],
        context_type=doc["context_type"],
        status=doc["status"],  # __post_init__ coerces the stored string to the enum
        value=doc.get("value"),
        source=doc.get("source"),
        last_confirmed_at=doc.get("last_confirmed_at"),
        updated_at=doc.get("updated_at"),
        notes=doc.get("notes"),
        metadata=doc.get("metadata") or {},
    )


def _school_information_to_doc(info: SchoolInformation) -> dict[str, Any]:
    return {
        "document_id": info.document_id,
        "structured_information": info.structured_information,
        "evidence": info.evidence,
        "source": info.source,
        "created_at": info.created_at,
    }


def _school_information_from_doc(doc: dict[str, Any]) -> SchoolInformation:
    return SchoolInformation(
        document_id=doc["document_id"],
        structured_information=doc.get("structured_information") or {},
        evidence=doc.get("evidence") or [],
        source=doc.get("source"),
        created_at=doc.get("created_at"),
    )


def _action_to_doc(action: Action) -> dict[str, Any]:
    return {
        "action_id": action.action_id,
        "child_id": action.child_id,
        "type": action.type.value,
        "status": action.status.value,
        "event_id": action.event_id,
        "reason": action.reason,
        "evidence": action.evidence,
        "due_at": action.due_at,
        "idempotency_key": action.idempotency_key,
        "external_resource_id": action.external_resource_id,
        "resolution": action.resolution,
        "created_at": action.created_at,
        "updated_at": action.updated_at,
    }


def _action_from_doc(doc: dict[str, Any]) -> Action:
    return Action(
        action_id=doc["action_id"],
        child_id=doc["child_id"],
        type=doc["type"],  # __post_init__ coerces stored strings to enums
        status=doc["status"],
        event_id=doc.get("event_id"),
        reason=doc.get("reason"),
        evidence=doc.get("evidence") or [],
        due_at=doc.get("due_at"),
        idempotency_key=doc.get("idempotency_key"),
        external_resource_id=doc.get("external_resource_id"),
        resolution=doc.get("resolution"),
        created_at=doc.get("created_at"),
        updated_at=doc.get("updated_at"),
    )


def _child_context_doc_id(child_id: str, context_type: str) -> str:
    # One context item per (child, type) — mirrors InMemoryRepository's key so both
    # backends have identical upsert semantics.
    return f"{child_id}::{context_type}"


class FirestoreRepository(Repository):
    """`Repository` backed by Cloud Firestore.

    Pass an explicit ``client`` to run against an emulator or a fake; otherwise use
    :meth:`from_settings` to build a production client from Application Default
    Credentials.
    """

    def __init__(self, client: Any) -> None:
        self._db = client

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> FirestoreRepository:
        settings = settings or Settings.from_env()
        from google.cloud import firestore

        client = firestore.Client(
            project=settings.project,
            database=settings.firestore_database,
        )
        return cls(client)

    # --- ChildContext ---
    def upsert_child_context(self, ctx: ChildContext) -> None:
        doc_id = _child_context_doc_id(ctx.child_id, ctx.context_type)
        self._db.collection(CHILD_CONTEXT_COLLECTION).document(doc_id).set(
            _child_context_to_doc(ctx)
        )

    def list_child_context(self, child_id: str) -> list[ChildContext]:
        query = self._db.collection(CHILD_CONTEXT_COLLECTION).where(
            filter=FieldFilter("child_id", "==", child_id)
        )
        return [_child_context_from_doc(snap.to_dict()) for snap in query.stream()]

    # --- SchoolInformation ---
    def upsert_school_information(self, info: SchoolInformation) -> None:
        self._db.collection(SCHOOL_INFORMATION_COLLECTION).document(info.document_id).set(
            _school_information_to_doc(info)
        )

    def get_school_information(self, document_id: str) -> SchoolInformation | None:
        snap = self._db.collection(SCHOOL_INFORMATION_COLLECTION).document(document_id).get()
        if not snap.exists:
            return None
        return _school_information_from_doc(snap.to_dict())

    # --- Actions ---
    def upsert_action(self, action: Action) -> None:
        self._db.collection(ACTIONS_COLLECTION).document(action.action_id).set(
            _action_to_doc(action)
        )

    def get_action(self, action_id: str) -> Action | None:
        snap = self._db.collection(ACTIONS_COLLECTION).document(action_id).get()
        if not snap.exists:
            return None
        return _action_from_doc(snap.to_dict())

    def list_actions(self, child_id: str) -> list[Action]:
        query = self._db.collection(ACTIONS_COLLECTION).where(
            filter=FieldFilter("child_id", "==", child_id)
        )
        return [_action_from_doc(snap.to_dict()) for snap in query.stream()]

    def get_action_by_idempotency_key(self, idempotency_key: str) -> Action | None:
        query = (
            self._db.collection(ACTIONS_COLLECTION)
            .where(filter=FieldFilter("idempotency_key", "==", idempotency_key))
            .limit(1)
        )
        for snap in query.stream():
            return _action_from_doc(snap.to_dict())
        return None
