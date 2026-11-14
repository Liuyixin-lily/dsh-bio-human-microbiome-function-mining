#!/usr/bin/env python3
"""Check that a finished run actually produced the delivery set, and say how to fill each gap.

The examples drifted: one had the full set in `outputs/task/`, one had only `combined.tsv` and
`scored.tsv`, one had per-species tables but no merged result, and one wrote its deliverables to a
different directory. Nothing detected that, so it was found by eye — which is exactly what this
script prevents.

Expected, under `<project-dir>/outputs/task/`:

- `final_target_candidates.tsv` (required; may be empty, but then the note must exist)
- `final_target_candidates_note.md` (required only when the final table is empty)
- `high_confidence_candidate_summary.tsv`
- `experimental_hypotheses.tsv`
- a scored table (`scored_candidates.tsv` / `scored_candidates_full.tsv` / `scored.tsv`)

Usage:

    python3 scripts/check_deliverables.py --project-dir ~/ex1_restart
    python3 scripts/check_deliverables.py --project-dir ~/ex1_restart --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TASK_DIR = Path("outputs") / "task"
SCORED_NAMES = ("scored_candidates_full.tsv", "scored_candidates.tsv", "scored.tsv")


def rows(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return max(0, sum(1 for _ in handle) - 1)


def check(project_dir: Path) -> list[dict[str, str]]:
    task = project_dir / TASK_DIR
    findings: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str, fix: str = "") -> None:
        findings.append({"file": name, "status": status, "detail": detail, "fix": fix})

    if not task.is_dir():
        add(str(TASK_DIR), "missing", "the task output directory does not exist",
            "run the screening and scoring steps, then scripts/summarize_candidates.py")
        return findings

    # a run may keep its scored table one level up (outputs/scored_candidates.tsv) rather than in
    # outputs/task; both are accepted, the deliverable set is what matters
    candidates = [task / name for name in SCORED_NAMES] + [
        project_dir / "outputs" / name for name in SCORED_NAMES
    ]
    scored = next((path for path in candidates if path.is_file()), None)
    if scored is None:
        add("scored table", "missing",
            f"none of {', '.join(SCORED_NAMES)} is present",
            "python3 scripts/score_candidates.py --input <combined>.tsv --project project.json "
            "--output outputs/task/scored_candidates.tsv")
    else:
        add(scored.name, "ok", f"{rows(scored)} row(s)")

    final = task / "final_target_candidates.tsv"
    if not final.is_file():
        add(final.name, "missing",
            "the delivery table is absent; a run that stops after scoring has no deliverable",
            "python3 scripts/summarize_candidates.py --scored <scored>.tsv --project project.json "
            "--outdir outputs/task")
    else:
        count = rows(final)
        add(final.name, "ok" if count else "empty", f"{count} row(s)")
        if count == 0:
            note = task / "final_target_candidates_note.md"
            if note.is_file():
                add(note.name, "ok", "explains the empty table")
            else:
                add(note.name, "missing",
                    "an empty final table without an explanation reads as 'nothing was found'",
                    "re-run summarize_candidates.py; it writes the note when the table is empty")

    for name in ("high_confidence_candidate_summary.tsv", "experimental_hypotheses.tsv"):
        path = task / name
        if path.is_file():
            add(name, "ok", f"{rows(path)} row(s)")
        else:
            add(name, "missing", "expected deliverable",
                "python3 scripts/summarize_candidates.py --scored <scored>.tsv "
                "--project project.json --outdir outputs/task")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a run produced the delivery set.")
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"error: not a directory: {args.project_dir}", file=sys.stderr)
        return 2
    findings = check(args.project_dir)
    problems = [f for f in findings if f["status"] in ("missing", "empty")]

    if args.json:
        print(json.dumps({"project_dir": str(args.project_dir), "findings": findings,
                          "problems": len(problems)}, ensure_ascii=False, indent=2))
        return 0 if not problems else 1

    print(f"{args.project_dir} / {TASK_DIR}")
    for finding in findings:
        mark = {"ok": "ok  ", "empty": "EMPTY", "missing": "MISS"}[finding["status"]]
        print(f"  [{mark}] {finding['file']}: {finding['detail']}")
        if finding["fix"]:
            print(f"          fix: {finding['fix']}")
    if problems:
        print(f"\n{len(problems)} problem(s): this run is not complete.")
        return 1
    print("\ncomplete: the delivery set is present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
