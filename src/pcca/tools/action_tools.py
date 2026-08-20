"""Action Tools — Calendar / Reminder / Gmail Draft.

Interface stubs (SOT-2738). Real execution with human approval, duplicate
prevention, and idempotency (External Resource ID / Idempotency Key) is
implemented in SOT-2742.

Boundaries the real implementation must honour:
  * Every external action requires human approval.
  * Gmail is **draft-only** — never auto-send.
  * Prevent duplicate creation of the same event / reminder / draft / action.
"""

from __future__ import annotations


def create_calendar_event(
    child_id: str, title: str, start: str, end: str, approved: bool = False
) -> dict:
    """Register a school event on the calendar (after human approval).

    Args:
        child_id: The child the event belongs to.
        title: Event title (e.g. "Zoo Field Trip").
        start: ISO-8601 start datetime.
        end: ISO-8601 end datetime.
        approved: Whether the parent has approved creating this event.

    Returns:
        A dict describing the (would-be) created event; duplicates are prevented.
    """

    return {
        "status": "not_implemented",
        "detail": "Calendar Tool is implemented in SOT-2742.",
        "child_id": child_id,
        "title": title,
        "start": start,
        "end": end,
        "approved": approved,
    }


def create_reminder(child_id: str, text: str, due_at: str, approved: bool = False) -> dict:
    """Create a parent reminder/task derived from a conflict or missing info.

    Args:
        child_id: The child the reminder relates to.
        text: What the parent must do (e.g. "Confirm medication arrangements").
        due_at: ISO-8601 due datetime (or a relative marker like "before_event").
        approved: Whether the parent has approved creating this reminder.

    Returns:
        A dict describing the (would-be) created reminder.
    """

    return {
        "status": "not_implemented",
        "detail": "Reminder Tool is implemented in SOT-2742.",
        "child_id": child_id,
        "text": text,
        "due_at": due_at,
        "approved": approved,
    }


def create_gmail_draft(child_id: str, subject: str, body: str) -> dict:
    """Create a Gmail **draft** for the parent to review (never auto-sent).

    Args:
        child_id: The child the enquiry relates to.
        subject: Draft subject line.
        body: Draft body.

    Returns:
        A dict describing the (would-be) created draft. Sending stays human-in-the-loop.
    """

    return {
        "status": "not_implemented",
        "detail": "Gmail Draft Tool is implemented in SOT-2742 (draft-only, no auto-send).",
        "child_id": child_id,
        "subject": subject,
        "body": body,
    }
