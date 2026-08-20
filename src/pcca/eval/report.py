"""Rendering helpers for :class:`pcca.eval.harness.EvalReport`."""

from __future__ import annotations

from pcca.eval.harness import EvalReport


def to_markdown(report: EvalReport) -> str:
    """Render a human-readable Markdown summary of the evaluation."""

    lines: list[str] = []
    lines.append("# Personal Child Context Agent — Evaluation Report")
    lines.append("")
    lines.append(
        f"- Scenarios: **{report.scenarios_passed}/{len(report.scenarios)} passed**"
    )
    lines.append(f"- Categories covered: **{len(report.coverage)}**")
    lines.append("")

    lines.append("## Metrics")
    lines.append("")
    lines.append("| Metric | Score | Ratio | Goal |")
    lines.append("| --- | --- | --- | --- |")
    for m in report.metrics:
        goal = "↑ higher" if m.higher_is_better else "↓ lower"
        ratio = f"{m.numerator:g}/{m.denominator:g}" if m.denominator else "n/a"
        lines.append(f"| {m.name} | {m.score:.3f} | {ratio} | {goal} |")
    lines.append("")

    lines.append("## Coverage")
    lines.append("")
    for category in sorted(report.coverage):
        lines.append(f"- `{category}`: {report.coverage[category]}")
    lines.append("")

    lines.append("## Scenarios")
    lines.append("")
    lines.append("| Scenario | Category | Region | Overall | Fired rules | Pass |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for s in report.scenarios:
        mark = "✅" if s.passed else "❌"
        region = s.region or "-"
        rules = ", ".join(s.fired_rules) or "-"
        lines.append(
            f"| {s.scenario_id} | {s.category} | {region} | {s.overall} | {rules} | {mark} |"
        )
    lines.append("")

    failing = [s for s in report.scenarios if not s.passed]
    if failing:
        lines.append("## Failures")
        lines.append("")
        for s in failing:
            lines.append(f"- **{s.scenario_id}**: {'; '.join(s.failures)}")
        lines.append("")

    return "\n".join(lines)
