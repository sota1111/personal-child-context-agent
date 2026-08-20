"""Evaluation harness + metrics (SOT-2744).

Runs the synthetic dataset through the deterministic Conflict Tool and, for
repository-representable scenarios, the full Agent Flow, then aggregates the safety
metrics named in the issue:

  * **Conflict Recall / Precision** — finding-rule level, over the ground-truth
    positive rules vs. what actually fired.
  * **Evidence Accuracy** — every finding and every planned action must carry the
    evidence it was derived from.
  * **Abstention (Unknown) Accuracy** — the agent surfaces information_missing /
    clarification exactly when it should (unknown ≠ safe), and does not abstain when
    a fact is explicitly known/absent.
  * **Personalization Accuracy** — the same document routed against three children
    (known_present / explicitly_absent / unknown) yields the right, *distinct*
    outcomes; in particular `unknown` is never collapsed into `explicitly_absent`.
  * **Unsupported Inference Rate** — fraction of "inference-inducing" scenarios where
    the agent made an ungrounded (e.g. medical) generalisation. Lower is better.
  * **Action Accuracy** — the flow plans the right tools, each action is
    evidence-linked, and the human-approval gate holds (nothing external without
    approval).
  * **Action Completion Accuracy** — approved calendar/reminder ⇒ COMPLETED with an
    external resource; approved Gmail ⇒ draft READY_FOR_REVIEW (never auto-sent);
    reprocessing dedupes; re-evaluation transitions resolved actions; an executor
    failure ⇒ FAILED (not COMPLETED).
  * **Document Processing Accuracy** — the Document Tool's parsed/failed status is
    detected correctly.

Everything is offline: :class:`InMemoryRepository` + :class:`MockActionExecutor`.

Design note (Conflict-Tool level for findings): the flow's Clarify step calls the
exact same :func:`pcca.tools.conflict_tool.evaluate`, so scoring the findings from a
direct ``evaluate`` call is faithful to the flow — and it additionally lets a genuine
present/absent *contradiction* (which the repository's one-per-type keys would
collapse) be evaluated. Action metrics still run through the real flow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from pcca.eval.dataset import NOW, Scenario, build_dataset
from pcca.flow import AgentFlow, FlowResult, build_flow
from pcca.models import Action, ActionStatus, ConflictFinding, most_severe
from pcca.persistence import InMemoryRepository
from pcca.tools.action_tools import (
    CalendarEventRequest,
    MockActionExecutor,
)
from pcca.tools.conflict_tool import evaluate as evaluate_conflict_findings
from pcca.tools.document_tool import build_school_information, extract_school_information

# Findings that are abstentions (the agent is not asserting safety).
_ABSTAIN_NAMES = frozenset({"INFORMATION_MISSING", "CLARIFICATION_REQUIRED"})
# The neutral "nothing matched" rule is not counted as a fired conflict finding.
_NEUTRAL_RULE = "no_relevant_match"


class _FailingExecutor(MockActionExecutor):
    """Executor whose external calls raise — for the Action-Tool-failure scenario."""

    def create_calendar_event(self, request: CalendarEventRequest) -> str:
        raise RuntimeError("calendar backend unavailable")


@dataclass
class _Tally:
    """A simple hit/total accumulator for a rate-style metric."""

    hits: float = 0.0
    total: float = 0.0
    notes: list[str] = field(default_factory=list)

    def add(self, ok: bool, note: str = "") -> None:
        self.total += 1
        if ok:
            self.hits += 1
        elif note:
            self.notes.append(note)

    def score(self, *, vacuous: float = 1.0) -> float:
        return self.hits / self.total if self.total else vacuous


@dataclass
class MetricScore:
    """One aggregated metric in the report."""

    name: str
    score: float
    numerator: float
    denominator: float
    higher_is_better: bool = True
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "score": round(self.score, 4),
            "numerator": self.numerator,
            "denominator": self.denominator,
            "higher_is_better": self.higher_is_better,
            "notes": self.notes,
        }


@dataclass
class ScenarioOutcome:
    """Per-scenario observations (for the detailed report)."""

    scenario_id: str
    category: str
    region: str | None
    detect_status: str
    overall: str | None
    fired_rules: list[str]
    passed: bool
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "category": self.category,
            "region": self.region,
            "detect_status": self.detect_status,
            "overall": self.overall,
            "fired_rules": self.fired_rules,
            "passed": self.passed,
            "failures": self.failures,
        }


@dataclass
class EvalReport:
    """The full evaluation report: metrics + per-scenario detail + coverage."""

    metrics: list[MetricScore]
    scenarios: list[ScenarioOutcome]
    coverage: dict[str, int]

    @property
    def scenarios_passed(self) -> int:
        return sum(1 for s in self.scenarios if s.passed)

    def metric(self, name: str) -> MetricScore:
        for m in self.metrics:
            if m.name == name:
                return m
        raise KeyError(name)

    def to_dict(self) -> dict[str, object]:
        return {
            "summary": {
                "scenarios_total": len(self.scenarios),
                "scenarios_passed": self.scenarios_passed,
                "categories_covered": len(self.coverage),
            },
            "metrics": [m.to_dict() for m in self.metrics],
            "coverage": self.coverage,
            "scenarios": [s.to_dict() for s in self.scenarios],
        }


# --- flow helpers -----------------------------------------------------------------


def _fresh_flow(
    sc: Scenario, now: datetime, *, fail: bool = False
) -> tuple[InMemoryRepository, AgentFlow]:
    repo = InMemoryRepository()
    for c in sc.contexts:
        repo.upsert_child_context(c.build(sc.scenario_id, now))
    executor = _FailingExecutor() if fail else MockActionExecutor()
    return repo, build_flow(repository=repo, executor=executor)


def _process(
    flow: AgentFlow, sc: Scenario, now: datetime, approvals: set[str] | None = None
) -> FlowResult:
    return flow.process_document(
        child_id=sc.scenario_id,
        document_id=sc.document_id,
        document_ref=sc.document_text,
        source=sc.source,
        approvals=approvals,
        now=now,
    )


def _action_well_formed(a: Action, document_id: str) -> tuple[bool, str]:
    """A tracked-but-unapproved action must be evidence-linked and side-effect-free."""

    if not a.evidence:
        return False, f"{a.type.value}: no evidence"
    if a.source_document_id != document_id:
        return False, f"{a.type.value}: not linked to source document"
    if a.external_resource_id is not None:
        return False, f"{a.type.value}: external side effect without approval"
    if a.status not in (ActionStatus.WAITING_FOR_PARENT, ActionStatus.WAITING_FOR_INFORMATION):
        return False, f"{a.type.value}: unexpected status {a.status.value}"
    return True, ""


# --- the evaluation ---------------------------------------------------------------


def run_evaluation(scenarios: list[Scenario] | None = None, now: datetime = NOW) -> EvalReport:
    """Run the dataset and return an aggregated :class:`EvalReport`."""

    scenarios = scenarios if scenarios is not None else build_dataset()

    conflict = _Tally()      # placeholder; recall/precision computed from tp/fp/fn
    tp = fp = fn = 0
    evidence = _Tally()
    abstention = _Tally()
    personalization = _Tally()
    action_acc = _Tally()
    action_completion = _Tally()
    doc_processing = _Tally()
    unsupported = _Tally()   # rate: hits = # inferences made (lower is better)

    outcomes: list[ScenarioOutcome] = []
    coverage: dict[str, int] = {}
    # For the personalization cross-check (unknown must differ from explicitly_absent).
    group_overall: dict[str, dict[str, str | None]] = {}

    for sc in scenarios:
        coverage[sc.category] = coverage.get(sc.category, 0) + 1
        failures: list[str] = []

        # --- Detect (Document Tool) ---
        detect = extract_school_information(sc.document_text, source=sc.source)
        detect_status = str(detect.get("status"))
        ok_detect = detect_status == sc.expected.detect_status
        doc_processing.add(ok_detect)
        if not ok_detect:
            failures.append(f"detect status {detect_status} != {sc.expected.detect_status}")

        # --- Clarify (Conflict Tool) — faithful to the flow's Clarify step ---
        school = build_school_information(sc.document_id, detect)
        contexts = [c.build(sc.scenario_id, now) for c in sc.contexts]
        findings: list[ConflictFinding] = evaluate_conflict_findings(school, contexts, now=now)
        fired = {f.rule for f in findings if f.rule != _NEUTRAL_RULE}
        overall = most_severe([f.classification for f in findings]).name if findings else None

        # Conflict Recall / Precision (finding-rule level).
        exp_pos = set(sc.expected.positive_rules)
        s_tp = len(fired & exp_pos)
        s_fn = len(exp_pos - fired)
        s_fp = len(fired - exp_pos)
        tp += s_tp
        fn += s_fn
        fp += s_fp
        if s_fn:
            failures.append(f"missing rules: {sorted(exp_pos - fired)}")
        if s_fp:
            failures.append(f"unexpected rules: {sorted(fired - exp_pos)}")

        # Overall classification match.
        expected_overall = sc.expected.overall_classification
        if expected_overall is not None and overall != expected_overall:
            failures.append(f"overall {overall} != {expected_overall}")

        # Evidence Accuracy (findings).
        for f in findings:
            if f.rule == _NEUTRAL_RULE:
                continue
            has_ev = bool(f.school_evidence or f.personal_context_evidence)
            evidence.add(has_ev, f"{sc.scenario_id}:{f.rule} finding without evidence")

        # Abstention Accuracy.
        system_abstains = any(f.classification.name in _ABSTAIN_NAMES for f in findings)
        if sc.expected.should_abstain is not None:
            want = sc.expected.should_abstain
            ok = system_abstains == want
            abstention.add(ok, f"{sc.scenario_id}: abstain={system_abstains} expected={want}")
            if not ok:
                failures.append("abstention mismatch")

        # Unsupported Inference Rate (only over inducer scenarios).
        if sc.unsupported_inference_case:
            made_inference = bool(fired) or bool(fired & set(sc.expected.forbidden_rules))
            unsupported.add(
                made_inference, f"{sc.scenario_id}: ungrounded inference {sorted(fired)}"
            )
            if made_inference:
                failures.append("unsupported inference made")
        # Forbidden rules firing anywhere is a failure.
        bad = fired & set(sc.expected.forbidden_rules)
        if bad:
            failures.append(f"forbidden rules fired: {sorted(bad)}")

        # Personalization Accuracy.
        if sc.personalization_group is not None:
            ok = overall == sc.expected.overall_classification
            personalization.add(ok, f"{sc.scenario_id}: overall {overall}")
            group_overall.setdefault(sc.personalization_group, {})[sc.scenario_id] = overall

        # --- Plan / Act / Track / Re-evaluate (flow) — Action metrics ---
        if sc.runs_flow:
            repo, flow = _fresh_flow(sc, now)
            result = _process(flow, sc, now)
            self_failures = _score_actions(sc, result, action_acc)
            failures.extend(self_failures)
            _score_completion(sc, now, action_completion, failures)

        passed = not failures
        outcomes.append(
            ScenarioOutcome(
                scenario_id=sc.scenario_id,
                category=sc.category,
                region=sc.region,
                detect_status=detect_status,
                overall=overall,
                fired_rules=sorted(fired),
                passed=passed,
                failures=failures,
            )
        )

    # Personalization cross-check: within each group, `unknown` (C) must differ from
    # `explicitly_absent` (B). Encoded by scenario-id suffix convention.
    for _group, by_id in group_overall.items():
        b = next((v for k, v in by_id.items() if "explicitly_absent" in k), None)
        c = next((v for k, v in by_id.items() if "unknown" in k), None)
        if b is not None and c is not None:
            personalization.add(b != c, f"unknown/absent collapsed: both {c}")

    metrics = [
        MetricScore("conflict_recall", tp / (tp + fn) if (tp + fn) else 1.0, tp, tp + fn),
        MetricScore("conflict_precision", tp / (tp + fp) if (tp + fp) else 1.0, tp, tp + fp),
        MetricScore(
            "evidence_accuracy",
            evidence.score(),
            evidence.hits,
            evidence.total,
            notes=evidence.notes,
        ),
        MetricScore(
            "abstention_accuracy",
            abstention.score(),
            abstention.hits,
            abstention.total,
            notes=abstention.notes,
        ),
        MetricScore(
            "personalization_accuracy",
            personalization.score(),
            personalization.hits,
            personalization.total,
            notes=personalization.notes,
        ),
        MetricScore(
            "unsupported_inference_rate",
            unsupported.score(vacuous=0.0),
            unsupported.hits,
            unsupported.total,
            higher_is_better=False,
            notes=unsupported.notes,
        ),
        MetricScore(
            "action_accuracy",
            action_acc.score(),
            action_acc.hits,
            action_acc.total,
            notes=action_acc.notes,
        ),
        MetricScore(
            "action_completion_accuracy",
            action_completion.score(),
            action_completion.hits,
            action_completion.total,
            notes=action_completion.notes,
        ),
        MetricScore(
            "document_processing_accuracy",
            doc_processing.score(),
            doc_processing.hits,
            doc_processing.total,
        ),
    ]
    # (conflict tally kept only to make intent explicit; recall/precision use tp/fp/fn.)
    del conflict

    return EvalReport(metrics=metrics, scenarios=outcomes, coverage=coverage)


def _score_actions(sc: Scenario, result: FlowResult, action_acc: _Tally) -> list[str]:
    """Score Action Accuracy: right tools planned + every action well-formed."""

    failures: list[str] = []
    produced = sorted(a.type.value for a in result.actions)
    expected = sorted(sc.expected.expected_action_tools)
    ok_set = produced == expected
    action_acc.add(ok_set, f"{sc.scenario_id}: actions {produced} != {expected}")
    if not ok_set:
        failures.append(f"actions {produced} != {expected}")

    for a in result.actions:
        ok, note = _action_well_formed(a, sc.document_id)
        action_acc.add(ok, f"{sc.scenario_id}: {note}")
        if not ok:
            failures.append(note)
    return failures


def _score_completion(sc: Scenario, now: datetime, tally: _Tally, failures: list[str]) -> None:
    """Score Action Completion Accuracy via the scenario's probes."""

    # Approve everything ⇒ correct terminal states.
    if sc.approve_all:
        repo, flow = _fresh_flow(sc, now)
        first = _process(flow, sc, now)
        keys = {p.key for p in first.planned}
        result = _process(flow, sc, now, approvals=keys)
        for a in result.actions:
            ok, note = _completion_ok(a)
            tally.add(ok, f"{sc.scenario_id}: {note}")
            if not ok:
                failures.append(f"completion: {note}")

    # An approved action whose executor fails ⇒ FAILED, no external resource.
    if sc.executor_fails:
        repo, flow = _fresh_flow(sc, now, fail=True)
        first = _process(flow, sc, now)
        cal = next((p for p in first.planned if p.tool == "calendar_event"), None)
        if cal is None:
            tally.add(False, f"{sc.scenario_id}: no calendar action to fail")
            failures.append("no calendar action to fail")
        else:
            result = _process(flow, sc, now, approvals={cal.key})
            cal_action = result.action_by_key(cal.key)
            ok = (
                cal_action is not None
                and cal_action.status is ActionStatus.FAILED
                and cal_action.external_resource_id is None
            )
            tally.add(ok, f"{sc.scenario_id}: executor failure not marked FAILED")
            if not ok:
                failures.append("executor failure not marked FAILED")

    # Reprocessing must not create duplicates.
    if sc.reprocess:
        repo, flow = _fresh_flow(sc, now)
        _process(flow, sc, now)
        before = {a.action_id for a in repo.list_actions(sc.scenario_id)}
        _process(flow, sc, now)
        after = {a.action_id for a in repo.list_actions(sc.scenario_id)}
        ok = before == after and len(after) == len(before)
        tally.add(ok, f"{sc.scenario_id}: reprocessing duplicated actions")
        if not ok:
            failures.append("reprocessing duplicated actions")

    # Re-evaluation transitions (or holds) waiting-for-information actions.
    if sc.reeval is not None:
        repo, flow = _fresh_flow(sc, now)
        _process(flow, sc, now)
        for c in sc.reeval.add_contexts:
            repo.upsert_child_context(c.build(sc.scenario_id, now))
        changed = flow.reevaluate_pending_actions(sc.scenario_id, now=now)
        if sc.reeval.expect_transition:
            ok = any(a.status is ActionStatus.READY_FOR_REVIEW for a in changed)
            tally.add(ok, f"{sc.scenario_id}: expected re-evaluation transition did not occur")
            if not ok:
                failures.append("re-evaluation did not transition")
        else:
            ok = changed == []
            tally.add(ok, f"{sc.scenario_id}: re-evaluation transitioned without new info")
            if not ok:
                failures.append("re-evaluation transitioned without new info")


def _completion_ok(a: Action) -> tuple[bool, str]:
    """Expected terminal state for an approved action."""

    kind = a.type.value
    if kind in ("calendar_event", "reminder"):
        if a.status is ActionStatus.COMPLETED and a.external_resource_id is not None:
            return True, ""
        return False, f"{kind}: approved but status={a.status.value}"
    if kind == "gmail_draft":
        # A draft is left for the parent to review & send — never auto-completed.
        if a.status is ActionStatus.READY_FOR_REVIEW:
            return True, ""
        return False, f"gmail_draft: status={a.status.value} (expected ready_for_review)"
    # Any other tracked action (e.g. waiting on info) is acceptable as-is.
    return True, ""
