"""Persistence layer — the persistent source of truth.

`InMemoryRepository` lets the whole skeleton run and be tested with no credentials.
`FirestoreRepository` (SOT-2739) is the Cloud Firestore-backed source of truth used
in production; `get_repository()` selects the backend from configuration.
"""

from pcca.persistence.firestore_repository import FirestoreRepository
from pcca.persistence.repository import InMemoryRepository, Repository, get_repository

__all__ = [
    "FirestoreRepository",
    "InMemoryRepository",
    "Repository",
    "get_repository",
]
