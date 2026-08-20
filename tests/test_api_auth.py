"""Serving-layer auth tests (SOT-2794).

Cover the session-cookie lifecycle and the allow-list gate without contacting
Firebase (``httpx.post`` is monkeypatched), mirroring おたよりナビ's auth tests.
"""

from __future__ import annotations

import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from pcca.api import auth
from pcca.api.app import create_app


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AUTH_SECRET", "test-secret-value-1234567890")
    monkeypatch.setenv("FIREBASE_API_KEY", "test-api-key")
    monkeypatch.setenv("ALLOWED_USER_EMAILS", "allowed@example.com")
    return TestClient(create_app())


def test_session_success_sets_cookie(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth.httpx, "post", lambda *a, **k: FakeResponse(200, {"email": "allowed@example.com"})
    )
    res = client.post(
        "/api/auth/session",
        json={"email": "allowed@example.com", "password": "correct-password"},
    )
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert "auth_token" in res.cookies


def test_session_invalid_credentials_returns_401(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auth.httpx,
        "post",
        lambda *a, **k: FakeResponse(400, {"error": {"message": "INVALID_LOGIN_CREDENTIALS"}}),
    )
    res = client.post(
        "/api/auth/session", json={"email": "allowed@example.com", "password": "wrong"}
    )
    assert res.status_code == 401
    assert "auth_token" not in res.cookies


def test_session_email_not_allowed_returns_403(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auth.httpx, "post", lambda *a, **k: FakeResponse(200, {"email": "intruder@example.com"})
    )
    res = client.post(
        "/api/auth/session",
        json={"email": "intruder@example.com", "password": "correct-password"},
    )
    assert res.status_code == 403
    assert "auth_token" not in res.cookies


def test_session_too_many_attempts_returns_429(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auth.httpx,
        "post",
        lambda *a, **k: FakeResponse(400, {"error": {"message": "TOO_MANY_ATTEMPTS_TRY_LATER"}}),
    )
    res = client.post("/api/auth/session", json={"email": "allowed@example.com", "password": "x"})
    assert res.status_code == 429


_SECRET = "test-secret-value-1234567890"
_OWNER = "0" * 32


def test_owner_id_is_stable_and_case_insensitive() -> None:
    assert auth.owner_id_for_email("A@B.com") == auth.owner_id_for_email("  a@b.com ")
    assert len(auth.owner_id_for_email("a@b.com")) == 32


def test_valid_session_returns_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    token = auth._build_session_token(_OWNER, _SECRET)
    assert auth.get_current_user(auth_token=token) == _OWNER


def test_tampered_signature_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    issued_at = int(time.time())
    token = f"{_OWNER}.{issued_at}.{'0' * 64}"
    with pytest.raises(HTTPException) as exc:
        auth.get_current_user(auth_token=token)
    assert exc.value.status_code == 401


def test_expired_session_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    monkeypatch.setenv("SESSION_MAX_AGE_SECONDS", "60")
    old = int(time.time()) - 3600
    token = auth._build_session_token(_OWNER, _SECRET, issued_at=old)
    with pytest.raises(HTTPException) as exc:
        auth.get_current_user(auth_token=token)
    assert exc.value.status_code == 401


def test_missing_cookie_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    with pytest.raises(HTTPException) as exc:
        auth.get_current_user(auth_token=None)
    assert exc.value.status_code == 401
