"""Shared serving dependencies (SOT-2794).

The repository is the persistent source of truth. We build it **once** per process
(``PCCA_PERSISTENCE`` selects memory vs Firestore) and reuse it across requests, so a
Firestore client isn't reconstructed on every call. Each request gets a fresh
:class:`~pcca.flow.AgentFlow` over that shared repository — the flow is cheap and
stateless, the repository is the durable part.
"""

from __future__ import annotations

from functools import lru_cache

from pcca.flow import AgentFlow
from pcca.persistence import Repository, get_repository


@lru_cache(maxsize=1)
def get_shared_repository() -> Repository:
    """Process-wide persistent source of truth, selected from configuration."""

    return get_repository()


def get_flow() -> AgentFlow:
    """A request-scoped flow over the shared repository (FastAPI dependency)."""

    return AgentFlow(repository=get_shared_repository())
