"""Agent tools, with clearly separated responsibilities.

Implementation status:
  - Document Tool  → implemented (SOT-2740)
  - Conflict Tool  → implemented (SOT-2741)
  - Action Tools   → interface stubs (SOT-2742)

Each tool is a plain function (ADK function-tool) with a docstring the Root Agent
uses to decide when to call it.
"""

from pcca.tools.action_tools import (
    create_calendar_event,
    create_gmail_draft,
    create_reminder,
)
from pcca.tools.conflict_tool import evaluate_conflict
from pcca.tools.document_tool import (
    build_school_information,
    extract_school_information,
)

__all__ = [
    "extract_school_information",
    "build_school_information",
    "evaluate_conflict",
    "create_calendar_event",
    "create_reminder",
    "create_gmail_draft",
]
