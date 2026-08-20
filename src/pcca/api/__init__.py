"""FastAPI serving layer (SOT-2794).

Exposes the deterministic Agent Flow (Detect → Clarify → Plan → Act → Track →
Re-evaluate) over HTTP for Cloud Run, following the おたよりナビ
(``toddler-private-rag``) backend structure:

* ``/health`` — unauthenticated Cloud Run startup/liveness probe.
* server-side signed session cookie (HMAC over ``AUTH_SECRET``) gated by
  ``ALLOWED_USER_EMAILS``; ``owner_id = sha256(email)``.
* Firestore as the persistent source of truth (``PCCA_PERSISTENCE=firestore``).
* Gemini via Vertex AI (no API key).

The serving layer preserves the agent's safety invariants: it makes no medical
judgement, never auto-executes a side effect without approval, keeps Evidence on
every response, and never treats ``unknown`` as safe. It only *transports* the
deterministic flow's results.
"""

from pcca.api.app import app, create_app

__all__ = ["app", "create_app"]
