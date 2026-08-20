"""Repository interface + in-memory implementation.

The Firestore backend (persistent source of truth) is implemented in SOT-2739; it
will implement this same `Repository` protocol so the rest of the agent is
storage-agnostic.
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


class InMemoryRepository(Repository):
    """Non-persistent implementation for local runs, tests, and CI (no auth)."""

    def __init__(self) -> None:
        self._child_context: dict[tuple[str, str], ChildContext] = {}
        self._school_info: dict[str, SchoolInformation] = {}
        self._actions: dict[str, Action] = {}

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

    def get_action(self, action_id: str) -> Action | None:
        return self._actions.get(action_id)

    def list_actions(self, child_id: str) -> list[Action]:
        return [a for a in self._actions.values() if a.child_id == child_id]


def get_repository(settings: Settings | None = None) -> Repository:
    """Select a backend from configuration.

    "memory" is the default. "firestore" is wired up in SOT-2739.
    """

    settings = settings or Settings.from_env()
    if settings.persistence == "firestore":
        raise NotImplementedError(
            "Firestore persistence is implemented in SOT-2739; set PCCA_PERSISTENCE=memory."
        )
    return InMemoryRepository()
