"""Smoke test: the ADK Root Agent starts and exposes its tool stubs.

Runs fully offline — building the agent does not contact Gemini/Vertex.
"""

from __future__ import annotations

from pcca.config import Settings
from pcca.root_agent import ROOT_AGENT_TOOLS, build_root_agent, root_agent


def test_module_level_root_agent_exists() -> None:
    assert root_agent is not None
    assert root_agent.name == "personal_child_context_agent"


def test_build_root_agent_wires_all_tools() -> None:
    agent = build_root_agent(Settings(model="gemini-2.5-flash"))
    tool_names = {getattr(t, "__name__", type(t).__name__) for t in agent.tools}
    assert tool_names == {
        "extract_school_information",
        "evaluate_conflict",
        "create_calendar_event",
        "create_reminder",
        "create_gmail_draft",
    }
    assert len(ROOT_AGENT_TOOLS) == 5


def test_root_agent_can_call_a_tool_stub() -> None:
    # The wired Python callables are directly invocable (Detect step entry point).
    out = ROOT_AGENT_TOOLS[0]("doc-ref")
    assert out["status"] == "not_implemented"
