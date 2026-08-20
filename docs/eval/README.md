# Evaluation dataset & metrics (SOT-2744)

A synthetic, fully-offline evaluation harness that makes the agent's quality
measurable. It runs a hand-authored scenario set through the deterministic Conflict
Tool and Agent Flow (in-memory repository + mock action executor — no Gemini/Vertex
or Firestore credentials) and aggregates the safety metrics that matter for this
product.

## Run it

```bash
python -m pcca.eval                 # Markdown report to stdout
python -m pcca.eval --json          # JSON report to stdout
python -m pcca.eval --out docs/eval # (re)write baseline.md + baseline.json
```

The committed baseline lives in [`baseline.md`](./baseline.md) /
[`baseline.json`](./baseline.json).

## What it measures

| Metric | Meaning | Goal |
| --- | --- | --- |
| `conflict_recall` / `conflict_precision` | Did the right Conflict-Tool rules fire, and only those? (finding-rule level) | ↑ |
| `evidence_accuracy` | Every finding and planned action carries the evidence it was derived from | ↑ |
| `abstention_accuracy` | The agent surfaces *information missing* / *clarification* exactly when it should (unknown ≠ safe), and doesn't abstain when a fact is known/absent | ↑ |
| `personalization_accuracy` | Same document × different child ⇒ correct, **distinct** outcomes; `unknown` (C) is never collapsed into `explicitly_absent` (B) | ↑ |
| `unsupported_inference_rate` | Fraction of inference-inducing scenarios where an ungrounded (e.g. medical) generalisation was made | ↓ |
| `action_accuracy` | The flow plans the right tools, each action is evidence-linked, and the human-approval gate holds (no external side effect without approval) | ↑ |
| `action_completion_accuracy` | Approved calendar/reminder ⇒ COMPLETED + external resource; approved Gmail ⇒ draft READY_FOR_REVIEW (never auto-sent); reprocessing dedupes; re-evaluation transitions resolved actions; executor failure ⇒ FAILED | ↑ |
| `document_processing_accuracy` | The Document Tool's `parsed` / `processing_failed` status is detected correctly | ↑ |

## Dataset

`pcca.eval.dataset.build_dataset()` returns the scenarios, each pairing synthetic
inputs (a school document + a child's Personal Context) with **exact** ground-truth
expectations. The catalogue covers: clear conflict, no conflict, missing personal
context, missing school information, stale personal context, inter-source
contradiction, false-positive inducer, unsupported-inference inducer, the
personalization A/B/C triad, pending action + new information (resolved & unresolved),
duplicate action, document processing failure, action-tool failure, and US / Australia
scenarios.

## Baseline

Because the tools are deterministic and the dataset encodes the *intended* behaviour,
the baseline is green (recall/precision/evidence/abstention/personalization/action =
1.0, unsupported-inference rate = 0.0). The harness's value is (a) a regression gate —
any drift flips a scenario to ❌ — and (b) an executable specification of the safety
contract. New behaviours should add scenarios here first.

### Notable engine behaviours the dataset encodes

* The Conflict Tool treats `activity` and `required_items` text as part of a "food
  event", so a document with an activity but no explicit allergy status yields
  `missing_allergen_info` (a grounded abstention — unknown ≠ safe). Scenarios that
  want to isolate another rule give the child an `explicitly_absent` food allergy.
* A dated notice with no start/end time still yields an (all-day) calendar action,
  because the flow combines a present date with a `00:00` default time.
