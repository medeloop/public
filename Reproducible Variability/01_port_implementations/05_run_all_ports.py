#!/usr/bin/env python3
"""
05_run_all_ports.py — run every port in `phase1/ports/*.yaml`, concatenate
the attrition tables, and emit `phase3/summary.md` + `phase3/attrition_all.csv`.

Usage:
    python scripts/05_run_all_ports.py [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PHASE3 = HERE.parent
ROOT = PHASE3.parent
PHASE1 = ROOT / "phase1"

sys.path.insert(0, str(PHASE3))

from runner.harness import run_port  # noqa: E402
from runner.mcp import MedeloopSession  # noqa: E402


def _noop_execute(*, user_id, medebook_id, query):  # noqa: ANN001
    return {"status": "done", "patient_count": None, "echo": query}


def _noop_poll(*, async_query_id, user_id, medebook_id):  # noqa: ANN001
    return {"status": "done"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--user-id", default="local-dry-run")
    parser.add_argument("--medebook-id", default="local-dry-run")
    args = parser.parse_args()

    session = MedeloopSession(
        user_id=args.user_id,
        medebook_id=args.medebook_id,
        execute=_noop_execute,
        poll=_noop_poll,
    )

    results = []
    for yaml_path in sorted((PHASE1 / "ports").glob("*.yaml")):
        out_dir = PHASE3 / "runs" / yaml_path.stem
        print(f"→ {yaml_path.stem}")
        r = run_port(session, yaml_path, out_dir, dry_run=args.dry_run)
        results.append(r)

    # attrition_all.csv
    all_csv = PHASE3 / "attrition_all.csv"
    with open(all_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "cohort_name", "step_index", "step_name", "df_name",
            "n_patients", "wallclock_s",
        ])
        for r in results:
            for s in r.steps:
                w.writerow([
                    r.cohort_name, s.index, s.name, s.df_name,
                    s.n_patients, f"{s.wallclock_s:.2f}",
                ])

    # summary.md
    summary_lines = ["# Phase 3 — Sub-study 1 summary\n\n"]
    summary_lines.append("| Cohort | Structure | Steps | Final n | Final df |\n|---|:---:|---:|---:|---|\n")
    for r in results:
        summary_lines.append(
            f"| `{r.cohort_name}` | {r.structure} | {len(r.steps)} | "
            f"{r.final_n or '?'} | `{r.final_df}` |\n"
        )
    summary_lines.append(
        "\n_Per-step attrition lives in `phase3/runs/<Cohort>/attrition.csv`; "
        "the concatenated view is `phase3/attrition_all.csv`._\n"
    )
    (PHASE3 / "summary.md").write_text("".join(summary_lines))

    print()
    print(f"attrition_all → {all_csv}")
    print(f"summary       → {PHASE3 / 'summary.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
