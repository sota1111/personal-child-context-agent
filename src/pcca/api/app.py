"""FastAPI application factory (SOT-2794).

Composes the serving layer following the おたよりナビ backend structure:
``/health`` (public probe) + ``/api/auth/*`` (public) + authenticated flow/child
routes. ``uvicorn pcca.api.app:app --host 0.0.0.0 --port 8080`` is the Cloud Run entry
point.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pcca.api import auth
from pcca.api.routers import children as children_router
from pcca.api.routers import flow as flow_router

logger = logging.getLogger(__name__)


def _parse_cors_origins() -> list[str]:
    """Parse allowed CORS origins.

    ``allow_credentials=True`` is incompatible with the ``*`` wildcard (credentialed
    requests from any origin would let anyone call the API), so ``*`` is dropped and an
    empty result falls back to the local dev origin.
    """

    raw = os.getenv("CORS_ORIGINS", "http://localhost:5173")
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    safe = [o for o in origins if o != "*"]
    if len(safe) != len(origins):
        logger.warning("CORS_ORIGINS contained '*'; ignored (incompatible with credentials).")
    return safe or ["http://localhost:5173"]


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Surface missing auth config early without blocking startup (Cloud Run health
    # probe still needs /health to answer). Secrets arrive via Secret Manager.
    for name in ("AUTH_SECRET", "ALLOWED_USER_EMAILS"):
        if not os.getenv(name):
            logger.warning("%s not configured", name)
    if not (os.getenv("FIREBASE_WEB_API_KEY") or os.getenv("FIREBASE_API_KEY")):
        logger.warning("FIREBASE_WEB_API_KEY / FIREBASE_API_KEY not configured")
    yield


def create_app() -> FastAPI:
    """Build the FastAPI app with health, auth, and authenticated flow/child routes."""

    app = FastAPI(title="Personal Child Context Agent API", lifespan=_lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_parse_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health_check() -> dict[str, str]:
        # Unauthenticated liveness/startup probe for Cloud Run — no external calls.
        return {"status": "ok"}

    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(flow_router.router, prefix="/api", tags=["flow"])
    app.include_router(children_router.router, prefix="/api", tags=["children"])

    return app


app = create_app()
