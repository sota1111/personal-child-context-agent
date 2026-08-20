"""Server-side session authentication (SOT-2794).

Mirrors the おたよりナビ (``toddler-private-rag``) auth design:

* email/password is verified **server-side** against Firebase Identity Toolkit REST
  (``accounts:signInWithPassword``); the password never touches our storage or logs.
* the verified email is checked against ``ALLOWED_USER_EMAILS`` (allow-list gate).
* a stable ``owner_id = sha256(email)`` is derived and placed in a signed session
  cookie ``<owner_id>.<issued_at>.<hmac>`` (HMAC over ``AUTH_SECRET``). Tampering the
  owner or the issue time breaks the signature; the issue time also enforces a
  server-side expiry.

Only ``/health`` and ``/api/auth/*`` are public; every other route depends on
:func:`get_current_user`, which returns the caller's ``owner_id`` (or raises 401).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter()

logger = logging.getLogger(__name__)

_APP_NAME = "personal-child-context-agent"

# Identity Toolkit REST endpoint for server-side email/password verification.
_SIGN_IN_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"

# Session lifetime (seconds). Default 7 days; override with SESSION_MAX_AGE_SECONDS.
_DEFAULT_SESSION_MAX_AGE = 7 * 24 * 60 * 60

COOKIE_NAME = "auth_token"


def owner_id_for_email(email: str) -> str:
    """Derive a stable ``owner_id`` from a verified email.

    The lower-cased, trimmed email's sha256 (first 32 hex chars). The email string
    itself is never stored or transmitted — only this deterministic id travels in the
    cookie alongside its signature.
    """

    normalized = (email or "").strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


def _get_firebase_api_key() -> str | None:
    return os.getenv("FIREBASE_WEB_API_KEY") or os.getenv("FIREBASE_API_KEY")


def _session_max_age_seconds() -> int:
    """Session lifetime in seconds; invalid/unset falls back to the default."""

    raw = os.getenv("SESSION_MAX_AGE_SECONDS")
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return _DEFAULT_SESSION_MAX_AGE


class SessionRequest(BaseModel):
    email: str
    password: str


def _sign(owner_id: str, secret: str, issued_at: int) -> str:
    """HMAC-sign ``owner_id`` + issue time with ``AUTH_SECRET`` (anti-tamper).

    Including ``issued_at`` in the signed message means altering the time breaks the
    signature, so the server can enforce an expiry it fully controls.
    """

    message = f"{_APP_NAME}-auth:{owner_id}:{issued_at}"
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def _build_session_token(owner_id: str, secret: str, issued_at: int | None = None) -> str:
    """Assemble the signed session token ``<owner_id>.<issued_at>.<sig>``."""

    if issued_at is None:
        issued_at = int(time.time())
    return f"{owner_id}.{issued_at}.{_sign(owner_id, secret, issued_at)}"


def get_current_user(auth_token: str | None = Cookie(None)) -> str:
    """Recover ``owner_id`` from the signed session cookie, or raise 401.

    The cookie is ``<owner_id>.<issued_at>.<hmac>``. The signature is verified and the
    issue time checked against the configured max age. This is the single gate every
    non-public route depends on, so an unauthenticated request always yields 401.
    """

    auth_secret = os.getenv("AUTH_SECRET")
    if not auth_secret or not auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    parts = auth_token.split(".")
    if len(parts) != 3 or not all(parts):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session",
        )
    owner_id, issued_at_raw, signature = parts
    try:
        issued_at = int(issued_at_raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session",
        ) from None
    expected = _sign(owner_id, auth_secret, issued_at)
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session",
        )
    if int(time.time()) - issued_at > _session_max_age_seconds():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired",
        )
    return owner_id


def _verify_with_firebase(email: str, password: str, api_key: str) -> str:
    """Verify email/password via Identity Toolkit REST; return the verified email.

    The password is never logged. Raises HTTPException on failure, mapping Firebase
    error codes to appropriate HTTP statuses without leaking credentials.
    """

    try:
        resp = httpx.post(
            _SIGN_IN_URL,
            params={"key": api_key},
            json={"email": email, "password": password, "returnSecureToken": True},
            timeout=10.0,
        )
    except httpx.HTTPError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is unavailable",
        ) from None

    if resp.status_code == 200:
        verified: str = resp.json().get("email", email)
        return verified

    error_message = ""
    try:
        error_message = resp.json().get("error", {}).get("message", "")
    except Exception:
        error_message = ""

    if "TOO_MANY_ATTEMPTS" in error_message:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts; please wait and try again",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password",
    )


def _require_auth_config() -> tuple[str, str, list[str]]:
    """Fetch and validate the auth configuration (secret / API key / allow-list)."""

    auth_secret = os.getenv("AUTH_SECRET")
    api_key = _get_firebase_api_key()
    allowed_emails_str = os.getenv("ALLOWED_USER_EMAILS", "")
    allowed_emails = [e.strip() for e in allowed_emails_str.split(",") if e.strip()]

    if not auth_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AUTH_SECRET not configured",
        )
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FIREBASE_WEB_API_KEY / FIREBASE_API_KEY not configured",
        )
    return auth_secret, api_key, allowed_emails


def _issue_session_response(
    email: str, auth_secret: str, allowed_emails: list[str]
) -> JSONResponse:
    """Enforce the allow-list, then issue a signed session cookie for the email."""

    if allowed_emails and email not in allowed_emails:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This email is not allowed",
        )

    owner_id = owner_id_for_email(email)
    token = _build_session_token(owner_id, auth_secret)
    is_production = os.getenv("APP_ENV", "local").lower() == "production"

    response = JSONResponse(content={"success": True, "email": email})
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=is_production,
        samesite="lax",
        max_age=_session_max_age_seconds(),
        path="/",
    )
    return response


@router.post("/session")
def create_session(request: SessionRequest) -> JSONResponse:
    """email/password → Firebase verify → allow-list → signed session cookie."""

    auth_secret, api_key, allowed_emails = _require_auth_config()
    email = _verify_with_firebase(request.email, request.password, api_key)
    return _issue_session_response(email, auth_secret, allowed_emails)


@router.post("/logout")
def logout() -> JSONResponse:
    response = JSONResponse(content={"success": True})
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return response


@router.get("/me")
def me(current_user: str = Depends(get_current_user)) -> dict[str, str]:
    """Return the authenticated caller's stable ``owner_id`` (401 if unauthenticated)."""

    return {"status": "authenticated", "owner_id": current_user}
