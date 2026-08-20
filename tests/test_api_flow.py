"""Serving-layer flow/child tests (SOT-2794).

Exercise the public probe, the auth gate on protected routes, and the end-to-end
Example Scenario (peanut allergy × peanut-butter field-trip lunch) over HTTP against
the in-memory repository.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pcca.api import auth
from pcca.api.app import create_app
from pcca.api.deps import get_shared_repository

_SECRET = "test-secret-value-1234567890"

# A field-trip notice whose provided lunch contains the child's known allergen.
_DOCUMENT = (
    "Event: Zoo Field Trip\n"
    "Date: 2026-09-15\n"
    "Start: 09:00\n"
    "End: 15:00\n"
    "Food: Peanut butter sandwiches provided by the school.\n"
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    monkeypatch.setenv("ALLOWED_USER_EMAILS", "allowed@example.com")
    # Fresh in-memory repository per test (the shared-repo cache is process-global).
    get_shared_repository.cache_clear()
    return TestClient(create_app())


def _authed(client: TestClient) -> TestClient:
    """Attach a valid session cookie to the client for the protected routes."""

    token = auth._build_session_token(auth.owner_id_for_email("allowed@example.com"), _SECRET)
    client.cookies.set(auth.COOKIE_NAME, token)
    return client


def test_health_is_public(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_protected_route_requires_auth(client: TestClient) -> None:
    # No cookie ⇒ 401 on a protected route.
    res = client.get("/api/children/child-a/context")
    assert res.status_code == 401
    res = client.post(
        "/api/documents:process",
        json={"child_id": "c", "document_id": "d", "document_ref": _DOCUMENT},
    )
    assert res.status_code == 401


def test_put_and_get_context_preserves_status(client: TestClient) -> None:
    _authed(client)
    put = client.put(
        "/api/children/child-a/context",
        json={
            "contexts": [
                {"context_type": "food_allergy", "status": "known_present", "value": "peanut"},
                {"context_type": "mobility", "status": "unknown"},
            ]
        },
    )
    assert put.status_code == 200
    got = client.get("/api/children/child-a/context")
    assert got.status_code == 200
    by_type = {c["context_type"]: c for c in got.json()["contexts"]}
    assert by_type["food_allergy"]["status"] == "known_present"
    # `unknown` is stored as unknown — never collapsed into an absence.
    assert by_type["mobility"]["status"] == "unknown"


def test_process_document_example_scenario(client: TestClient) -> None:
    _authed(client)
    client.put(
        "/api/children/child-a/context",
        json={
            "contexts": [
                {"context_type": "food_allergy", "status": "known_present", "value": "peanut"}
            ]
        },
    )
    res = client.post(
        "/api/documents:process",
        json={
            "child_id": "child-a",
            "document_id": "doc-1",
            "document_ref": _DOCUMENT,
            "source": "pdf",
        },
    )
    assert res.status_code == 200
    body = res.json()
    # The peanut allergen match must produce a finding and a tracked, evidence-backed
    # action — and it must NOT be auto-executed (no approval was given).
    assert body["classification"] is not None
    assert body["findings"], "expected at least one conflict finding"
    assert body["actions"], "expected at least one tracked action"
    for action in body["actions"]:
        assert action["evidence"], "every action must retain evidence"
        assert action["status"] != "completed", "no action is completed without approval"


def test_reevaluate_endpoint_returns_changed_actions(client: TestClient) -> None:
    _authed(client)
    res = client.post("/api/actions:reevaluate", json={"child_id": "child-a"})
    assert res.status_code == 200
    body = res.json()
    assert body["child_id"] == "child-a"
    assert body["reevaluated"] == []  # nothing pending yet
