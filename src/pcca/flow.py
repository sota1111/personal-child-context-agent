"""Agent Flow orchestration — Detect → Clarify → Plan → Act → Track → Re-evaluate.

Implements SOT-2743: the Root Agent's integration layer. It wires the
responsibility-separated tools (Document / Conflict / Action) and the persistent
source of truth (repository / Firestore) into the one control flow that turns a
school document into tracked, evidence-backed, human-gated actions — and keeps the
unresolved ones alive so new information can re-evaluate them.

Why a deterministic orchestrator (not the LLM):
  The project's whole philosophy is "prefer deterministic over LLM, keep it offline
  and testable". The Conflict/Document/Action tools are already deterministic; this
  layer sequences them deterministically too, so the end-to-end Example Scenario runs
  in CI without Gemini/Vertex or Firestore credentials. The ADK ``LlmAgent`` in
  :mod:`pcca.root_agent` remains the interactive entry point (the ``adk`` CLI); it
  exposes the same tools and is expected to drive the same six steps at run time.

Safety invariants this flow preserves (inherited from the tools it calls):
  * **Human approval gates every external side effect.** An un-approved planned
    action is *recorded and tracked* (so it persists and is re-evaluated) but never
    touches the outside world and never becomes ``COMPLETED``.
  * **The agent never self-``COMPLETED``s on a safety judgement.** Re-evaluation only
    ever moves an action forward to ``READY_FOR_REVIEW`` (for a human to decide);
    ``COMPLETED`` only comes from an approved Action Tool execution.
  * **``unknown`` is never treated as safe.** ``INFORMATION_MISSING`` findings become
    tracked ``WAITING_FOR_INFORMATION`` actions, not silently dropped.
  * **Idempotency ⇒ resumable.** Every planned action has a deterministic idempotency
    key, so re-processing the same document after an interruption re-creates the same
    actions (deduped) and never double-executes an already-carried-out one.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pcca.models import (
    Action,
    ActionStatus,
    ActionType,
    ConflictClassification,
    SchoolInformation,
)
from pcca.persistence import Repository, get_repository
from pcca.tools.action_tools import (
    ActionExecutor,
    MockActionExecutor,
    create_calendar_event,
    create_gmail_draft,
    create_reminder,
)
from pcca.tools.conflict_tool import evaluate as evaluate_conflict_findings
from pcca.tools.document_tool import build_school_information, extract_school_information

# Conflict-Tool rules that, while unresolved, put an action into
# WAITING_FOR_INFORMATION — i.e. the action is waiting for a fact to arrive, and
# re-evaluation can clear it once the fact is known. Everything else that needs a
# human decision is WAITING_FOR_PARENT.
_INFO_MISSING_STATUS = ActionStatus.WAITING_FOR_INFORMATION


@dataclass(frozen=True)
class PlannedAction:
    """One action the flow decided to take, before it is tracked/executed.

    The ``key`` is both the planning identity and the Action Tool idempotency key, so
    the same planned action is never created or executed twice.
    """

    key: str
    tool: str  # "calendar_event" | "reminder" | "gmail_draft"
    action_type: ActionType
    waiting_status: ActionStatus  # status held while unapproved / awaiting info
    reason: str
    payload: dict[str, Any]  # tool-specific kwargs (title/start/end, text/due_at, ...)
    evidence: list[str] = field(default_factory=list)
    finding_rule: str | None = None
    due_at: datetime | None = None


@dataclass
class FlowResult:
    """Structured outcome of processing one document, step by step."""

    child_id: str
    document_id: str
    detect: dict[str, Any]
    classification: str | None
    findings: list[dict[str, Any]]
    planned: list[PlannedAction]
    actions: list[Action]  # tracked persistent actions after Act/Track
    reevaluated: list[Action]  # actions whose status changed during Re-evaluate

    def action_by_key(self, key: str) -> Action | None:
        for a in self.actions:
            if a.idempotency_key == key:
                return a
        return None


class AgentFlow:
    """Deterministic Root-Agent orchestration over the tools + repository.

    Injectable ``repository`` / ``executor`` keep the whole flow offline-testable
    (in-memory repo, mock executor) exactly like the individual tools.
    """

    def __init__(
        self,
        repository: Repository | None = None,
        executor: ActionExecutor | None = None,
    ) -> None:
        self.repository = repository or get_repository()
        self.executor = executor or MockActionExecutor()

    # -- the whole flow for one document ------------------------------------------

    def process_document(
        self,
        *,
        child_id: str,
        document_id: str,
        document_ref: str,
        source: str = "unknown",
        approvals: Iterable[str] | None = None,
        now: datetime | None = None,
    ) -> FlowResult:
        """Run Detect → Clarify → Plan → Act → Track → Re-evaluate for one document.

        Args:
            child_id: The child whose Personal Context to reconcile against.
            document_id: Stable id to store/track this document under.
            document_ref: Raw document text or a path to a UTF-8 text file.
            source: Provenance of the document (``"email"`` / ``"pdf"`` / ...).
            approvals: Idempotency keys of the planned actions the parent has
                approved. Anything not listed is tracked but NOT executed.
            now: Timestamp for created/updated records (never fabricated when omitted).

        Returns:
            A :class:`FlowResult` capturing every step's output.
        """

        approved_keys = set(approvals or ())

        # 1. Detect — structured extraction, then Track the document as source of truth.
        detect = extract_school_information(document_ref, source=source)
        school = build_school_information(document_id, detect)
        school.created_at = school.created_at or now
        self.repository.upsert_school_information(school)

        # 2. Clarify — reconcile against the child's Personal Context (deterministic).
        contexts = self.repository.list_child_context(child_id)
        findings = evaluate_conflict_findings(school, contexts, now=now)
        overall = _most_severe_name(findings)

        # 3. Plan — turn findings into concrete, evidence-backed actions.
        planned = self.plan_actions(child_id, document_id, school, findings)

        # 4/5. Act + Track — persist every planned action; execute only the approved
        # ones (human-approval gate). Nothing external happens without approval.
        tracked: list[Action] = []
        for pa in planned:
            action = self._track_and_maybe_act(
                child_id=child_id,
                document_id=document_id,
                planned=pa,
                approved=pa.key in approved_keys,
                now=now,
            )
            tracked.append(action)

        # 6. Re-evaluate — new document ⇒ revisit this child's still-open actions and
        # transition any whose missing information is now available.
        reevaluated = self.reevaluate_pending_actions(child_id, now=now)

        # Reflect any re-evaluation status changes in the returned action list.
        by_id = {a.action_id: a for a in tracked}
        for a in reevaluated:
            by_id[a.action_id] = a

        return FlowResult(
            child_id=child_id,
            document_id=document_id,
            detect=detect,
            classification=overall,
            findings=[f.to_dict() for f in findings],
            planned=planned,
            actions=list(by_id.values()),
            reevaluated=reevaluated,
        )

    # -- Plan ----------------------------------------------------------------------

    def plan_actions(
        self,
        child_id: str,
        document_id: str,
        school: SchoolInformation,
        findings: list[Any],
    ) -> list[PlannedAction]:
        """Map conflict findings (+ the event itself) to planned actions.

        Deterministic and side-effect-free. Duplicate planned actions (same key) are
        collapsed so several findings of the same rule yield a single action.
        """

        si = school.structured_information or {}
        event = _as_text(si.get("event")) or "the school event"
        start_iso = _combine_iso(si.get("date"), si.get("start_time"))
        end_iso = _combine_iso(si.get("date"), si.get("end_time"))
        due_iso = start_iso or _combine_iso(si.get("date"), None)
        due_dt = _parse_iso(due_iso)

        planned: dict[str, PlannedAction] = {}

        def add(pa: PlannedAction) -> None:
            planned.setdefault(pa.key, pa)

        # A calendar event for the trip itself — only when the document actually
        # states a date + start + end (never fabricate a time window).
        if start_iso and end_iso:
            add(
                PlannedAction(
                    key=self._key(child_id, "calendar_event", document_id),
                    tool="calendar_event",
                    action_type=ActionType.CALENDAR_EVENT,
                    waiting_status=ActionStatus.WAITING_FOR_PARENT,
                    reason=f"Add '{event}' to the calendar.",
                    payload={"title": event, "start": start_iso, "end": end_iso},
                    evidence=_event_evidence(si),
                    finding_rule=None,
                    due_at=_parse_iso(end_iso),
                )
            )

        for f in findings:
            classification = f.classification
            if classification is ConflictClassification.NO_RELEVANT_MATCH_FOUND:
                continue
            evidence = list(f.school_evidence) + list(f.personal_context_evidence)

            if classification is ConflictClassification.INFORMATION_MISSING:
                # Waiting for a fact ⇒ a school enquiry draft, tracked as
                # WAITING_FOR_INFORMATION so re-evaluation can later clear it.
                add(
                    PlannedAction(
                        key=self._key(child_id, "gmail_draft", document_id, f.rule),
                        tool="gmail_draft",
                        action_type=ActionType.GMAIL_DRAFT,
                        waiting_status=_INFO_MISSING_STATUS,
                        reason=f.reason,
                        payload={
                            "subject": f"Question about {event}",
                            "body": (
                                f"Hello, regarding {event}: {f.reason} "
                                "Could you please confirm? Thank you."
                            ),
                        },
                        evidence=evidence,
                        finding_rule=f.rule,
                        due_at=due_dt,
                    )
                )
            else:
                # CONFIRMED_RELEVANCE / CLARIFICATION_REQUIRED ⇒ a parent reminder to
                # act on / reconcile the finding. Requires approval; never auto-done.
                add(
                    PlannedAction(
                        key=self._key(child_id, "reminder", document_id, f.rule),
                        tool="reminder",
                        action_type=ActionType.REMINDER,
                        waiting_status=ActionStatus.WAITING_FOR_PARENT,
                        reason=f.reason,
                        payload={
                            "text": f"[{event}] {f.reason}",
                            "due_at": due_iso or "",
                        },
                        evidence=evidence,
                        finding_rule=f.rule,
                        due_at=due_dt,
                    )
                )

        return list(planned.values())

    # -- Act + Track ---------------------------------------------------------------

    def _track_and_maybe_act(
        self,
        *,
        child_id: str,
        document_id: str,
        planned: PlannedAction,
        approved: bool,
        now: datetime | None,
    ) -> Action:
        """Persist the planned action, then execute it only if approved.

        Tracking first (with the re-evaluation linkage) guarantees the action is
        durable — and carries the info the re-evaluation step needs — whether or not
        it is approved, and makes the whole step resumable/idempotent.
        """

        # Track: create (deduped) the persistent action in its waiting status.
        existing = self.repository.get_action_by_idempotency_key(planned.key)
        if existing is None:
            existing = Action(
                action_id=_action_id(planned.key),
                child_id=child_id,
                type=planned.action_type,
                status=planned.waiting_status,
                reason=planned.reason,
                evidence=list(planned.evidence),
                due_at=planned.due_at,
                idempotency_key=planned.key,
                source_document_id=document_id,
                finding_rule=planned.finding_rule,
                created_at=now,
                updated_at=now,
            )
            self.repository.create_action(existing)

        if not approved:
            return existing

        # Act: approved ⇒ perform the real (mock in CI) side effect via the tool,
        # reusing the same idempotency key so the tool updates THIS action and the
        # duplicate/idempotency guard applies.
        self._execute(child_id=child_id, planned=planned, now=now)
        # Re-read the action the tool mutated (status / external_resource_id).
        return self.repository.get_action_by_idempotency_key(planned.key) or existing

    def _execute(
        self, *, child_id: str, planned: PlannedAction, now: datetime | None
    ) -> dict[str, Any]:
        """Dispatch an approved planned action to its Action Tool."""

        p = planned.payload
        if planned.tool == "calendar_event":
            return create_calendar_event(
                child_id,
                p["title"],
                p["start"],
                p["end"],
                approved=True,
                repository=self.repository,
                executor=self.executor,
                idempotency_key=planned.key,
                reason=planned.reason,
                evidence=planned.evidence,
                now=now,
            )
        if planned.tool == "reminder":
            return create_reminder(
                child_id,
                p["text"],
                p["due_at"],
                approved=True,
                repository=self.repository,
                executor=self.executor,
                idempotency_key=planned.key,
                reason=planned.reason,
                evidence=planned.evidence,
                now=now,
            )
        if planned.tool == "gmail_draft":
            return create_gmail_draft(
                child_id,
                p["subject"],
                p["body"],
                approved=True,
                repository=self.repository,
                executor=self.executor,
                idempotency_key=planned.key,
                reason=planned.reason,
                evidence=planned.evidence,
                now=now,
            )
        raise ValueError(f"unknown tool {planned.tool!r}")

    # -- Re-evaluate ---------------------------------------------------------------

    def reevaluate_pending_actions(
        self, child_id: str, now: datetime | None = None
    ) -> list[Action]:
        """Revisit this child's open actions and transition any now-resolvable ones.

        For each action still ``WAITING_FOR_INFORMATION`` (i.e. blocked on a missing
        fact), re-run the Conflict Tool against its source document with the *current*
        Personal Context. If the exact rule that created it no longer fires, the
        missing information has arrived ⇒ move it to ``READY_FOR_REVIEW`` for a human.
        The agent never advances an action to ``COMPLETED`` here.
        """

        contexts = self.repository.list_child_context(child_id)
        changed: list[Action] = []

        for action in self.repository.list_actions(child_id):
            if action.status is not ActionStatus.WAITING_FOR_INFORMATION:
                continue
            if not action.source_document_id or not action.finding_rule:
                continue
            school = self.repository.get_school_information(action.source_document_id)
            if school is None:
                continue

            findings = evaluate_conflict_findings(school, contexts, now=now)
            rules_now = {f.rule for f in findings}
            if action.finding_rule not in rules_now:
                action.status = ActionStatus.READY_FOR_REVIEW
                action.resolution = (
                    "New information resolved the previously-missing fact; "
                    "ready for parent review."
                )
                action.updated_at = now
                self.repository.upsert_action(action)
                changed.append(action)

        return changed

    # -- helpers -------------------------------------------------------------------

    @staticmethod
    def _key(*parts: Any) -> str:
        raw = "\x1f".join("" if p is None else str(p) for p in parts)
        return "flow-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def build_flow(
    repository: Repository | None = None, executor: ActionExecutor | None = None
) -> AgentFlow:
    """Construct the deterministic orchestration flow (see :class:`AgentFlow`)."""

    return AgentFlow(repository=repository, executor=executor)


# --- module-level helpers ---------------------------------------------------------


def _most_severe_name(findings: list[Any]) -> str | None:
    from pcca.models import most_severe

    if not findings:
        return None
    return most_severe([f.classification for f in findings]).name


def _event_evidence(si: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for f in ("event", "date", "start_time", "end_time"):
        if si.get(f) not in (None, "", []):
            out.append(f"{f}: {_as_text(si[f])}")
    return out


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value)


def _combine_iso(date: Any, time: Any) -> str | None:
    """Combine a ``YYYY-MM-DD`` date and optional ``HH:MM`` time into an ISO string.

    Returns ``None`` unless the date is present and parseable — we never fabricate a
    date/time the document did not state.
    """

    date_s = _as_text(date).strip()
    if not date_s:
        return None
    try:
        d = datetime.fromisoformat(date_s).date()
    except ValueError:
        return None
    time_s = _as_text(time).strip()
    hh, mm = 0, 0
    if time_s:
        import re

        m = re.search(r"(\d{1,2}):(\d{2})", time_s)
        if m:
            hh, mm = int(m.group(1)), int(m.group(2))
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                hh, mm = 0, 0
    return datetime(d.year, d.month, d.day, hh, mm).isoformat()


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _action_id(key: str) -> str:
    return "act-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
