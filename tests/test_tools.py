"""Tool interface-stub tests.

These assert the stub contracts (shapes) so later issues can replace the bodies
without breaking the Root Agent wiring.
"""

from __future__ import annotations

from pcca.tools import (
    create_calendar_event,
    create_gmail_draft,
    create_reminder,
)

# The Document Tool (SOT-2740) and Conflict Tool (SOT-2741) are implemented; their
# behaviour is covered by tests/test_document_tool.py and tests/test_conflict_tool.py.
# The Action Tools below are still interface stubs (SOT-2742).


def test_action_tools_stub_shapes() -> None:
    assert create_calendar_event("child-a", "Zoo", "2026-09-18T10:30", "2026-09-18T14:30")[
        "status"
    ] == "not_implemented"
    assert create_reminder("child-a", "Confirm meds", "before_event")["status"] == "not_implemented"
    draft = create_gmail_draft("child-a", "Allergen info", "Please provide ingredients.")
    assert draft["status"] == "not_implemented"
    # Gmail stays draft-only; the stub never claims to have sent anything.
    assert "draft-only" in draft["detail"]
