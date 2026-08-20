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

# All tools are implemented: Document (SOT-2740), Conflict (SOT-2741), Action
# (SOT-2742). Full behaviour lives in the per-tool test modules; this module keeps a
# thin interface smoke test that the wired tools default to the safe, no-side-effect
# path (human approval required) so the Root Agent wiring can never silently regress.


def test_action_tools_default_to_pending_approval() -> None:
    # Called with the default (in-memory) backend and no approval: no external effect.
    cal = create_calendar_event("child-a", "Zoo", "2026-09-18T10:30", "2026-09-18T14:30")
    assert cal["status"] == "pending_approval"
    assert cal["external_resource_id"] is None

    rem = create_reminder("child-a", "Confirm meds", "2026-09-17T09:00")
    assert rem["status"] == "pending_approval"

    draft = create_gmail_draft("child-a", "Allergen info", "Please provide ingredients.")
    assert draft["status"] == "pending_approval"
    # Gmail stays draft-only; it never claims to have sent anything.
    assert draft["sent"] is False
