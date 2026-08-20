"""Persistence layer — the persistent source of truth.

`InMemoryRepository` lets the whole skeleton run and be tested with no credentials.
The Firestore-backed implementation is added in SOT-2739; `get_repository()`
selects the backend from configuration.
"""

from pcca.persistence.repository import InMemoryRepository, Repository, get_repository

__all__ = ["InMemoryRepository", "Repository", "get_repository"]
