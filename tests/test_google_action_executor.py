"""Real Google executor tests (SOT-2799).

Drives :class:`GoogleActionExecutor` with an ``httpx.MockTransport`` so the real
Calendar / Gmail-draft / Tasks HTTP paths are exercised with no credentials, and
verifies it end-to-end through the Action Tools (approval gate + idempotency around
the real executor):

  * approved calendar/gmail/reminder actions call the right Google endpoint and keep
    the returned ``external_resource_id``;
  * an UN-approved action never touches the network (draft/event not created);
  * the same approved action is not created twice (idempotency / duplicate guard);
  * Gmail uses the *drafts* endpoint only — no send endpoint is ever called, and the
    encoded message round-trips to the given subject/body;
  * Calendar sends a deterministic client id and treats a 409 as already-created;
  * a non-2xx response raises → the tool records the action FAILED (no crash);
  * ``build_action_executor`` selects mock by default and the Google executor on opt-in.
"""

from __future__ import annotations

import base64
from datetime import datetime
from email import message_from_bytes

import httpx
import pytest

from pcca.config import Settings
from pcca.models import ActionStatus
from pcca.persistence import InMemoryRepository
from pcca.tools import create_calendar_event, create_gmail_draft, create_reminder
from pcca.tools.action_tools import (
    STATUS_CREATED,
    STATUS_DUPLICATE,
    STATUS_FAILED,
    STATUS_PENDING_APPROVAL,
    GoogleActionExecutor,
    MockActionExecutor,
    build_action_executor,
)

NOW = datetime(2026, 8, 20, 9, 0, 0)


class _Recorder:
    """Captures every request an httpx.MockTransport handler sees."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []


def _make_executor(
    handler,
    *,
    recorder: _Recorder | None = None,
    **kwargs,
) -> GoogleActionExecutor:
    rec = recorder or _Recorder()

    def _wrapped(request: httpx.Request) -> httpx.Response:
        rec.requests.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(_wrapped))
    return GoogleActionExecutor(
        http_client=client,
        access_token_provider=lambda: "test-token",
        **kwargs,
    )


# --- calendar ---------------------------------------------------------------------


def test_approved_calendar_event_hits_calendar_api_and_keeps_resource_id() -> None:
    rec = _Recorder()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert "/calendar/v3/calendars/primary/events" in str(request.url)
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(200, json={"id": "cal-evt-123"})

    executor = _make_executor(handler, recorder=rec)
    repo = InMemoryRepository()

    result = create_calendar_event(
        "child-1",
        "Zoo Field Trip",
        "2026-09-01T09:00:00",
        "2026-09-01T15:00:00",
        approved=True,
        repository=repo,
        executor=executor,
        now=NOW,
    )

    assert result["status"] == STATUS_CREATED
    assert result["external_resource_id"] == "cal-evt-123"
    assert len(rec.requests) == 1
    action = repo.get_action(result["action_id"])
    assert action is not None
    assert action.status is ActionStatus.COMPLETED
    assert action.external_resource_id == "cal-evt-123"
    assert action.event_id == "cal-evt-123"


def test_calendar_sends_deterministic_id_and_409_is_idempotent() -> None:
    rec = _Recorder()

    def handler(request: httpx.Request) -> httpx.Response:
        # Emulate the event already existing for this client-supplied id.
        return httpx.Response(409, json={"error": {"message": "duplicate"}})

    executor = _make_executor(handler, recorder=rec)
    repo = InMemoryRepository()

    result = create_calendar_event(
        "child-1",
        "Zoo Field Trip",
        "2026-09-01T09:00:00",
        "2026-09-01T15:00:00",
        approved=True,
        repository=repo,
        executor=executor,
        now=NOW,
    )

    body = rec.requests[0].read().decode()
    assert '"id":' in body and "pcca" in body  # deterministic client id was supplied
    # 409 (already created) is a success outcome: the action keeps a resource id.
    assert result["status"] == STATUS_CREATED
    assert result["external_resource_id"].startswith("pcca")


# --- approval gate + idempotency around the real executor -------------------------


def test_unapproved_action_never_touches_the_network() -> None:
    rec = _Recorder()

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("executor was called for an un-approved action")

    executor = _make_executor(handler, recorder=rec)
    repo = InMemoryRepository()

    result = create_calendar_event(
        "child-1",
        "Zoo Field Trip",
        "2026-09-01T09:00:00",
        "2026-09-01T15:00:00",
        approved=False,
        repository=repo,
        executor=executor,
        now=NOW,
    )

    assert result["status"] == STATUS_PENDING_APPROVAL
    assert result["external_resource_id"] is None
    assert rec.requests == []


def test_same_approved_action_is_not_created_twice() -> None:
    rec = _Recorder()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": f"cal-{len(rec.requests)}"})

    executor = _make_executor(handler, recorder=rec)
    repo = InMemoryRepository()
    args = ("child-1", "Zoo Field Trip", "2026-09-01T09:00:00", "2026-09-01T15:00:00")

    kw = dict(approved=True, repository=repo, executor=executor, now=NOW)
    first = create_calendar_event(*args, **kw)
    second = create_calendar_event(*args, **kw)

    assert first["status"] == STATUS_CREATED
    assert second["status"] == STATUS_DUPLICATE
    assert second["external_resource_id"] == first["external_resource_id"]
    # Exactly one real API call despite two approved invocations.
    assert len(rec.requests) == 1


# --- gmail draft-only -------------------------------------------------------------


def test_gmail_creates_draft_only_and_round_trips_message() -> None:
    rec = _Recorder()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        # The ONLY Gmail endpoint touched is drafts — never send.
        assert url.endswith("/gmail/v1/users/me/drafts")
        assert "/send" not in url
        return httpx.Response(200, json={"id": "draft-xyz", "message": {"id": "msg-1"}})

    executor = _make_executor(handler, recorder=rec, gmail_recipient="school@example.com")
    repo = InMemoryRepository()

    result = create_gmail_draft(
        "child-1",
        "Field trip medication",
        "Please confirm the medication arrangements.",
        approved=True,
        repository=repo,
        executor=executor,
        now=NOW,
    )

    assert result["status"] == STATUS_CREATED
    assert result["external_resource_id"] == "draft-xyz"
    assert result["sent"] is False

    # The action is left for the parent to review & send — never auto-completed.
    action = repo.get_action(result["action_id"])
    assert action is not None
    assert action.status is ActionStatus.READY_FOR_REVIEW

    # Decode message.raw and verify subject/body/recipient round-trip.
    payload = rec.requests[0].read()
    import json

    raw = json.loads(payload)["message"]["raw"]
    message = base64.urlsafe_b64decode(raw)
    decoded = message_from_bytes(message)
    assert decoded["Subject"] == "Field trip medication"
    assert decoded["To"] == "school@example.com"
    assert b"confirm the medication" in message


def test_no_send_endpoint_or_scope_exists() -> None:
    """Draft-only invariant: no send endpoint is constructed, no send scope requested."""

    from pcca.tools.action_tools import GOOGLE_ACTION_SCOPES

    # No Gmail send scope is ever requested — only compose (draft) capability.
    assert not any("gmail.send" in scope for scope in GOOGLE_ACTION_SCOPES)
    assert any("gmail.compose" in scope for scope in GOOGLE_ACTION_SCOPES)

    # No code path builds a Gmail send URL (drafts/send or messages/send).
    import pcca.tools.action_tools as mod

    source = __import__("inspect").getsource(mod)
    assert "drafts/send" not in source
    assert "messages/send" not in source
    # GoogleActionExecutor exposes only draft creation, never a send method.
    assert not hasattr(mod.GoogleActionExecutor, "send_gmail")
    assert not any(
        "send" in name.lower() for name in dir(mod.GoogleActionExecutor) if not name.startswith("_")
    )


# --- reminder / tasks -------------------------------------------------------------


def test_approved_reminder_hits_tasks_api() -> None:
    rec = _Recorder()

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/tasks/v1/lists/@default/tasks" in str(request.url)
        return httpx.Response(200, json={"id": "task-9"})

    executor = _make_executor(handler, recorder=rec)
    repo = InMemoryRepository()

    result = create_reminder(
        "child-1",
        "Confirm medication arrangements",
        "2026-09-01T08:00:00",
        approved=True,
        repository=repo,
        executor=executor,
        now=NOW,
    )

    assert result["status"] == STATUS_CREATED
    assert result["external_resource_id"] == "task-9"
    body = rec.requests[0].read().decode()
    assert "Confirm medication arrangements" in body
    assert "2026-09-01T08:00:00" in body  # due passed through


# --- failure handling -------------------------------------------------------------


def test_http_error_marks_action_failed_without_crashing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "backend down"}})

    executor = _make_executor(handler)
    repo = InMemoryRepository()

    result = create_calendar_event(
        "child-1",
        "Zoo Field Trip",
        "2026-09-01T09:00:00",
        "2026-09-01T15:00:00",
        approved=True,
        repository=repo,
        executor=executor,
        now=NOW,
    )

    assert result["status"] == STATUS_FAILED
    assert result["external_resource_id"] is None
    action = repo.get_action(result["action_id"])
    assert action is not None
    assert action.status is ActionStatus.FAILED


# --- executor selection -----------------------------------------------------------


def test_build_action_executor_defaults_to_mock() -> None:
    assert isinstance(build_action_executor(Settings()), MockActionExecutor)


@pytest.mark.parametrize("choice", ["google", "real", "GOOGLE", " Real "])
def test_build_action_executor_selects_google_on_opt_in(monkeypatch, choice) -> None:
    built: dict[str, object] = {}

    def _fake_from_settings(settings):
        built["settings"] = settings
        return "GOOGLE_EXECUTOR"

    monkeypatch.setattr(
        GoogleActionExecutor,
        "from_settings",
        classmethod(lambda cls, s: _fake_from_settings(s)),
    )
    result = build_action_executor(Settings(action_executor=choice))
    assert result == "GOOGLE_EXECUTOR"
    assert built["settings"].action_executor == choice
