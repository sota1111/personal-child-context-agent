"""Runtime configuration.

Gemini is accessed through **Vertex AI** using Application Default Credentials, so
no API key is stored. All values default to safe, offline-friendly settings so the
skeleton runs and its tests pass without any credentials.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Resolved configuration for the agent."""

    # Gemini via Vertex AI.
    use_vertexai: bool = True
    project: str | None = None
    location: str = "us-central1"
    model: str = "gemini-2.5-flash"

    # Persistence: "memory" (default, no auth) or "firestore" (SOT-2739).
    persistence: str = "memory"
    firestore_database: str = "(default)"

    # Action execution (SOT-2799): "mock" (default, offline, no external side effect)
    # or "google"/"real" to perform real Google Calendar / Gmail Draft / Tasks calls.
    # The default stays "mock" so nothing touches the outside world without opt-in.
    action_executor: str = "mock"
    # Which Google resources the real executor writes to (used only when
    # action_executor selects the real one). Defaults mirror the Google API defaults.
    google_calendar_id: str = "primary"
    gmail_user_id: str = "me"
    google_task_list_id: str = "@default"
    # Optional default "To" address for Gmail drafts (e.g. the school). When unset the
    # draft is created without a recipient for the parent to fill in — still draft-only.
    gmail_recipient: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            use_vertexai=_env_bool("GOOGLE_GENAI_USE_VERTEXAI", True),
            project=os.getenv("GOOGLE_CLOUD_PROJECT"),
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
            model=os.getenv("PCCA_MODEL", "gemini-2.5-flash"),
            persistence=os.getenv("PCCA_PERSISTENCE", "memory"),
            firestore_database=os.getenv("FIRESTORE_DATABASE", "(default)"),
            action_executor=os.getenv("PCCA_ACTION_EXECUTOR", "mock"),
            google_calendar_id=os.getenv("PCCA_GOOGLE_CALENDAR_ID", "primary"),
            gmail_user_id=os.getenv("PCCA_GMAIL_USER_ID", "me"),
            google_task_list_id=os.getenv("PCCA_GOOGLE_TASK_LIST_ID", "@default"),
            gmail_recipient=os.getenv("PCCA_GMAIL_RECIPIENT") or None,
        )
