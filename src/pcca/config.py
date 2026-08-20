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

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            use_vertexai=_env_bool("GOOGLE_GENAI_USE_VERTEXAI", True),
            project=os.getenv("GOOGLE_CLOUD_PROJECT"),
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
            model=os.getenv("PCCA_MODEL", "gemini-2.5-flash"),
            persistence=os.getenv("PCCA_PERSISTENCE", "memory"),
            firestore_database=os.getenv("FIRESTORE_DATABASE", "(default)"),
        )
