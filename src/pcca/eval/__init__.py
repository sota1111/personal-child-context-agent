"""Synthetic evaluation harness for the Personal Child Context Agent (SOT-2744).

This package makes the agent's quality *measurable*: a synthetic dataset of
scenarios (with ground-truth expectations) plus a metrics harness that runs each
scenario through the deterministic tools/flow and aggregates the numbers that
matter for this product's safety boundaries — Conflict Recall/Precision, Evidence
Accuracy, Abstention (Unknown) Accuracy, Personalization Accuracy, Unsupported
Inference Rate, Action Accuracy and Action Completion Accuracy.

Everything runs offline (in-memory repository + mock action executor), so a full
baseline can be produced in CI without Gemini/Vertex or Firestore credentials.

Entry points:
  * :func:`pcca.eval.dataset.build_dataset` — the synthetic scenarios.
  * :func:`pcca.eval.harness.run_evaluation` — run the dataset and get a report.
  * ``python -m pcca.eval`` — run the harness and print/emit the report.
"""

from __future__ import annotations

from pcca.eval.dataset import Scenario, build_dataset
from pcca.eval.harness import EvalReport, MetricScore, run_evaluation

__all__ = [
    "Scenario",
    "build_dataset",
    "EvalReport",
    "MetricScore",
    "run_evaluation",
]
