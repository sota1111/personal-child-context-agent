"""CLI: run the synthetic evaluation and emit a report.

Usage::

    python -m pcca.eval                 # print the Markdown report to stdout
    python -m pcca.eval --json          # print the JSON report to stdout
    python -m pcca.eval --out docs/eval # write baseline.md + baseline.json there

All offline — no credentials required.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pcca.eval.harness import run_evaluation
from pcca.eval.report import to_markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the PCCA synthetic evaluation harness.")
    parser.add_argument("--json", action="store_true", help="print the JSON report to stdout")
    parser.add_argument(
        "--out",
        metavar="DIR",
        help="write baseline.md and baseline.json into DIR",
    )
    args = parser.parse_args(argv)

    report = run_evaluation()

    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "baseline.json").write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (out_dir / "baseline.md").write_text(to_markdown(report) + "\n", encoding="utf-8")
        print(f"Wrote {out_dir / 'baseline.json'} and {out_dir / 'baseline.md'}")

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    elif not args.out:
        print(to_markdown(report))

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
