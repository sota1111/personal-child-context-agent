"""A minimal in-memory fake of the Cloud Firestore client.

It implements just the surface `FirestoreRepository` uses — ``collection`` /
``document`` / ``set`` / ``get`` / ``where(filter=FieldFilter)`` / ``limit`` /
``stream`` — so the repository's CRUD and idempotency logic can be tested without
GCP credentials or an emulator. Documents are deep-copied on write and read, so a
stored document behaves like a real remote round-trip (no shared references).
"""

from __future__ import annotations

import copy
from typing import Any


class _FakeSnapshot:
    def __init__(self, data: dict[str, Any] | None) -> None:
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._data) if self._data is not None else None


class _FakeDocumentRef:
    def __init__(self, store: dict[str, dict[str, Any]], doc_id: str) -> None:
        self._store = store
        self._id = doc_id

    def set(self, data: dict[str, Any]) -> None:
        self._store[self._id] = copy.deepcopy(data)

    def get(self) -> _FakeSnapshot:
        return _FakeSnapshot(self._store.get(self._id))

    def delete(self) -> None:
        self._store.pop(self._id, None)


class _FakeQuery:
    def __init__(self, store: dict[str, dict[str, Any]], filters: list[tuple[str, Any]]) -> None:
        self._store = store
        self._filters = filters
        self._limit: int | None = None

    def where(self, *, filter: Any) -> _FakeQuery:  # noqa: A002 - mirrors firestore API
        if filter.op_string != "==":
            raise NotImplementedError(f"fake supports only '==', got {filter.op_string!r}")
        return _FakeQuery(self._store, [*self._filters, (filter.field_path, filter.value)])

    def limit(self, n: int) -> _FakeQuery:
        q = _FakeQuery(self._store, self._filters)
        q._limit = n
        return q

    def stream(self):
        count = 0
        for data in self._store.values():
            if all(data.get(field) == value for field, value in self._filters):
                yield _FakeSnapshot(data)
                count += 1
                if self._limit is not None and count >= self._limit:
                    return


class _FakeCollection:
    def __init__(self, store: dict[str, dict[str, Any]]) -> None:
        self._store = store

    def document(self, doc_id: str) -> _FakeDocumentRef:
        return _FakeDocumentRef(self._store, doc_id)

    def where(self, *, filter: Any) -> _FakeQuery:  # noqa: A002 - mirrors firestore API
        return _FakeQuery(self._store, []).where(filter=filter)


class FakeFirestoreClient:
    """Stands in for ``google.cloud.firestore.Client`` in tests."""

    def __init__(self) -> None:
        self._collections: dict[str, dict[str, dict[str, Any]]] = {}

    def collection(self, name: str) -> _FakeCollection:
        return _FakeCollection(self._collections.setdefault(name, {}))
