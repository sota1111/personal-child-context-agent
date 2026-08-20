"""ADK Root Agent skeleton.

The Root Agent orchestrates the workflow only — it is **not** the source of truth.
Facts and action state live in the persistence layer (Firestore in production).

It wires the responsibility-separated tools (Document / Conflict / Action) and
targets Gemini via Vertex AI. Construction is offline (no network / credentials),
so the skeleton and its smoke test run in CI without any secrets.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from google.adk.agents import LlmAgent

from pcca.config import Settings
from pcca.tools import (
    create_calendar_event,
    create_gmail_draft,
    create_reminder,
    evaluate_conflict,
    extract_school_information,
)

ROOT_AGENT_INSTRUCTION = """\
You are the Personal Child Context Agent. Reconcile generic school information with
a specific child's personal context and drive the flow:
Detect -> Clarify -> Plan -> Act -> Track -> Re-evaluate.

Hard rules:
- You are orchestration only. Never treat your own memory as the source of truth;
  facts and action state come from the persistence layer.
- Make no medical judgements. Never assert "safe", "can eat", or "no risk".
- `unknown` is not `explicitly_absent` and is never treated as safe.
- Only relate facts explicitly present in the child's personal context; do not
  infer medical concerns from general knowledge.
- Prefer deterministic tool results over guessing.
- Personal-context changes and external actions require human approval.
  Gmail is draft-only; never auto-send.
- Keep evidence for every conflict and action.
"""

# Tools exposed to the Root Agent, grouped by responsibility.
ROOT_AGENT_TOOLS: list[Callable[..., Any]] = [
    extract_school_information,  # Document Tool
    evaluate_conflict,           # Conflict Tool
    create_calendar_event,       # Action Tool: Calendar
    create_reminder,             # Action Tool: Reminder
    create_gmail_draft,          # Action Tool: Gmail Draft
]


def build_root_agent(settings: Settings | None = None) -> LlmAgent:
    """Construct the ADK Root Agent with its tools wired up.

    No network calls or credentials are required to build the agent; Gemini/Vertex
    is only contacted when the agent is actually run.
    """

    settings = settings or Settings.from_env()
    return LlmAgent(
        name="personal_child_context_agent",
        model=settings.model,
        instruction=ROOT_AGENT_INSTRUCTION,
        description=(
            "Reconciles generic school information with a child's personal context "
            "and drives Detect -> Clarify -> Plan -> Act -> Track -> Re-evaluate."
        ),
        # ADK accepts plain callables as function tools; cast bridges the invariant
        # list element type expected by LlmAgent.
        tools=cast("list[Any]", ROOT_AGENT_TOOLS),
    )


# ADK's `adk` CLI / web looks for a module-level `root_agent`.
root_agent = build_root_agent()
