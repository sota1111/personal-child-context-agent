"""Evaluation harness tests (SOT-2744).

Verify the synthetic dataset covers the required scenario catalogue and that the
harness computes every metric — including the personalization A/B/C distinction, the
Unsupported Inference and Abstention measurements — fully offline.
"""

from __future__ import annotations

from pcca.eval import build_dataset, run_evaluation
from pcca.eval.harness import EvalReport
from pcca.eval.report import to_markdown

# The scenario categories SOT-2744 requires the dataset to contain.
REQUIRED_CATEGORIES = {
    "clear_conflict",
    "no_conflict",
    "missing_personal_context",
    "missing_school_information",
    "stale_personal_context",
    "source_contradiction",
    "false_positive",
    "unsupported_inference",
    "personalization",
    "pending_resolved",
    "pending_unresolved",
    "duplicate_action",
    "document_processing_failure",
    "action_tool_failure",
    "region_us",
    "region_au",
}

# Every metric named in the issue must be produced with a numeric score.
REQUIRED_METRICS = {
    "conflict_recall",
    "conflict_precision",
    "evidence_accuracy",
    "abstention_accuracy",
    "personalization_accuracy",
    "unsupported_inference_rate",
    "action_accuracy",
    "action_completion_accuracy",
    "document_processing_accuracy",
}


def test_dataset_covers_required_scenarios() -> None:
    categories = {s.category for s in build_dataset()}
    missing = REQUIRED_CATEGORIES - categories
    assert not missing, f"dataset missing scenario categories: {sorted(missing)}"


def test_dataset_scenario_ids_are_unique() -> None:
    scenarios = build_dataset()
    ids = [s.scenario_id for s in scenarios]
    assert len(ids) == len(set(ids))
    # And every document id is unique so flow runs never collide.
    doc_ids = [s.document_id for s in scenarios]
    assert len(doc_ids) == len(set(doc_ids))


def test_harness_computes_all_metrics_numerically() -> None:
    report = run_evaluation()
    names = {m.name for m in report.metrics}
    assert REQUIRED_METRICS <= names
    for m in report.metrics:
        assert isinstance(m.score, float)
        assert 0.0 <= m.score <= 1.0


def test_us_and_australia_scenarios_present() -> None:
    regions = {s.region for s in build_dataset() if s.region}
    assert {"US", "AU"} <= regions


def test_personalization_unknown_not_treated_as_absent() -> None:
    """Child C (unknown) must NOT get the same outcome as child B (explicitly absent)."""

    report = run_evaluation()
    outcomes = {s.scenario_id: s for s in report.scenarios}
    b = outcomes["personalization_B_explicitly_absent"]
    c = outcomes["personalization_C_unknown"]
    a = outcomes["personalization_A_known_present"]

    assert a.overall == "CONFIRMED_RELEVANCE"
    assert b.overall == "NO_RELEVANT_MATCH_FOUND"
    assert c.overall == "INFORMATION_MISSING"
    assert c.overall != b.overall
    # The dedicated metric captures this too.
    assert report.metric("personalization_accuracy").score == 1.0


def test_unsupported_inference_is_measured_and_zero() -> None:
    """Asthma alone must never flag the petting zoo — the ungrounded-inference rate is 0."""

    report = run_evaluation()
    rate = report.metric("unsupported_inference_rate")
    assert rate.denominator >= 1  # at least one inducer scenario is scored
    assert rate.higher_is_better is False
    assert rate.score == 0.0


def test_abstention_is_measured() -> None:
    report = run_evaluation()
    abst = report.metric("abstention_accuracy")
    assert abst.denominator >= 1
    assert abst.score == 1.0


def test_baseline_all_scenarios_pass() -> None:
    """The authored ground truth matches the current deterministic behaviour."""

    report = run_evaluation()
    failing = [s.scenario_id for s in report.scenarios if not s.passed]
    assert not failing, f"regressions in: {failing}"


def test_conflict_recall_and_precision_are_perfect_on_baseline() -> None:
    report = run_evaluation()
    assert report.metric("conflict_recall").score == 1.0
    assert report.metric("conflict_precision").score == 1.0


def test_action_completion_covers_transitions_and_dedup() -> None:
    """Approved terminal states, dedup, re-evaluation and executor-failure are all scored."""

    report = run_evaluation()
    completion = report.metric("action_completion_accuracy")
    assert completion.denominator >= 4  # approve/fail/reprocess/reeval probes all contribute
    assert completion.score == 1.0


def test_report_renders_markdown_and_dict() -> None:
    report = run_evaluation()
    md = to_markdown(report)
    assert "Evaluation Report" in md
    assert "conflict_recall" in md

    d = report.to_dict()
    assert d["summary"]["scenarios_total"] == len(report.scenarios)
    assert isinstance(d["metrics"], list)


def test_report_is_an_evalreport() -> None:
    report = run_evaluation()
    assert isinstance(report, EvalReport)
