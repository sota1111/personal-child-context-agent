"""Repository interface + in-memory implementation.

The Firestore backend (persistent source of truth) lives in
:mod:`pcca.persistence.firestore_repository`; it implements this same `Repository`
protocol so the rest of the agent is storage-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pcca.config import Settings
from pcca.models import Action, ChildContext, SchoolInformation


class Repository(ABC):
    """Storage-agnostic persistence for the agent's source of truth."""

    # --- ChildContext ---
    @abstractmethod
    def upsert_child_context(self, ctx: ChildContext) -> None: ...

    @abstractmethod
    def list_child_context(self, child_id: str) -> list[ChildContext]: ...

    # --- SchoolInformation ---
    @abstractmethod
    def upsert_school_information(self, info: SchoolInformation) -> None: ...

    @abstractmethod
    def get_school_information(self, document_id: str) -> SchoolInformation | None: ...

    # --- Actions ---
    @abstractmethod
    def upsert_action(self, action: Action) -> None: ...

    @abstractmethod
    def get_action(self, action_id: str) -> Action | None: ...

    @abstractmethod
    def list_actions(self, child_id: str) -> list[Action]: ...

    @abstractmethod
    def get_action_by_idempotency_key(self, idempotency_key: str) -> Action | None: ...

    def create_action(self, action: Action) -> Action:
        """Idempotent create: never persist a duplicate for the same key.

        If ``action.idempotency_key`` is set and an action already exists for that
        key, the **existing** action is returned unchanged and nothing is written.
        Otherwise the action is persisted and returned. Actions without an
        idempotency key are always written (the caller opted out of dedup).

        Subclasses may override for a storage-native atomic guarantee, but this base
        implementation is correct for any backend that implements the abstract
        methods above.
        """

        if action.idempotency_key is not None:
            existing = self.get_action_by_idempotency_key(action.idempotency_key)
            if existing is not None:
                return existing
        self.upsert_action(action)
        return action


class InMemoryRepository(Repository):
    """Non-persistent implementation for local runs, tests, and CI (no auth)."""

    def __init__(self) -> None:
        self._child_context: dict[tuple[str, str], ChildContext] = {}
        self._school_info: dict[str, SchoolInformation] = {}
        self._actions: dict[str, Action] = {}
        # idempotency_key -> action_id, for duplicate-creation prevention.
        self._action_keys: dict[str, str] = {}

    def upsert_child_context(self, ctx: ChildContext) -> None:
        self._child_context[(ctx.child_id, ctx.context_type)] = ctx

    def list_child_context(self, child_id: str) -> list[ChildContext]:
        return [c for (cid, _), c in self._child_context.items() if cid == child_id]

    def upsert_school_information(self, info: SchoolInformation) -> None:
        self._school_info[info.document_id] = info

    def get_school_information(self, document_id: str) -> SchoolInformation | None:
        return self._school_info.get(document_id)

    def upsert_action(self, action: Action) -> None:
        self._actions[action.action_id] = action
        if action.idempotency_key is not None:
            self._action_keys[action.idempotency_key] = action.action_id

    def get_action(self, action_id: str) -> Action | None:
        return self._actions.get(action_id)

    def list_actions(self, child_id: str) -> list[Action]:
        return [a for a in self._actions.values() if a.child_id == child_id]

    def get_action_by_idempotency_key(self, idempotency_key: str) -> Action | None:
        action_id = self._action_keys.get(idempotency_key)
        return self._actions.get(action_id) if action_id is not None else None


def get_repository(settings: Settings | None = None) -> Repository:
    """Select a backend from configuration.

    ``"memory"`` (default) needs no credentials. ``"firestore"`` returns the
    persistent source of truth backed by Cloud Firestore (SOT-2739).
    """

    settings = settings or Settings.from_env()
    if settings.persistence == "firestore":
        # Imported lazily so the default in-memory path never requires the Firestore
        # client to be constructable (no credentials in CI / local dev).
        from pcca.persistence.firestore_repository import FirestoreRepository

        return FirestoreRepository.from_settings(settings)
    return InMemoryRepository()
