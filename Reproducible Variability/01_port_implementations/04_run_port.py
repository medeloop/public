#!/usr/bin/env python3
"""
04_run_port.py — execute a single port end-to-end against Medeloop.

Usage (from within a Medeloop-enabled Cowork session, where the MCP callables
are resolvable):

    python scripts/04_run_port.py --port Master_implementation
    python scripts/04_run_port.py --port Team_3 --dry-run

Dry-run mode does not call the Medeloop MCP; it only renders the prompts
and writes them to `phase3/runs/<Cohort>/step_log.jsonl` so the human
reviewer can inspect the exact text that would be sent.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PHASE3 = HERE.parent
ROOT = PHASE3.parent
PHASE1 = ROOT / "phase1"

sys.path.insert(0, str(PHASE3))

from runner.harness import run_port  # noqa: E402
from runner.mcp import MedeloopSession  # noqa: E402


def _noop_execute(*, user_id, medebook_id, query):  # noqa: D401, ANN001
    """Placeholder — in the live Cowork session this is replaced with the
    actual MCP tool callable."""
    return {"status": "done", "patient_count": None, "echo": query}


def _noop_poll(*, async_query_id, user_id, medebook_id):  # noqa: D401, ANN001
    return {"status": "done"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, help="Cohort name (e.g. Master_implementation).")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--user-id", default="local-dry-run")
    parser.add_argument("--medebook-id", default="local-dry-run")
    args = parser.parse_args()

    yaml_path = PHASE1 / "ports" / f"{args.port}.yaml"
    if not yaml_path.exists():
        print(f"port yaml not found: {yaml_path}", file=sys.stderr)
        return 1

    out_dir = PHASE3 / "runs" / args.port

    session = MedeloopSession(
        user_id=args.user_id,
        medebook_id=args.medebook_id,
        execute=_noop_execute,
        poll=_noop_poll,
    )

    result = run_port(session, yaml_path, out_dir, dry_run=args.dry_run)
    print(f"cohort={result.cohort_name}  structure={result.structure}")
    print(f"steps={len(result.steps)}  final_df={result.final_df}  "
          f"final_n={result.final_n}")
    print(f"attrition → {out_dir / 'attrition.csv'}")
    print(f"step_log  → {out_dir / 'step_log.jsonl'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
