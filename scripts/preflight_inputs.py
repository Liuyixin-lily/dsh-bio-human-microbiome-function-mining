#!/usr/bin/env python3
"""Check candidate microbial inputs before heavy external tools are run.

The plugin intentionally does not install external tools. This helper only
checks the project-defined inputs and never creates or fabricates missing
files. Configured candidate proteome and per-genome protein/CDS/GenBank/
structure paths are validated. Candidate annotation and target-file paths stay
optional unless a strict route flag enables them.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

FIELDS = ["path", "kind", "status", "note", "resolved_path"]


def resolve_path(value: str, root: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def load_project(path: Path) -> tuple[dict[str, Any], Path]:
    if path.is_dir():
        path = path / "project.json"
    if not path.is_file():
        raise SystemExit(f"project file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"failed to read project JSON: {exc}")
    return data, path.parent.resolve()


def configured_genome_inputs(project: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Return genome, kind, path, and whether kind may be optional."""
    rows = []
    kinds = {
        "protein_fasta": ("file", False),
        "cds_fasta": ("file", True),
        "fna": ("file", True),
        "gbff": ("file", True),
        "structure_dir": ("directory", True),
    }
    genomes = (project.get("candidate_sequences") or {}).get("genomes") or {}
    if not isinstance(genomes, dict):
        raise SystemExit("candidate_sequences.genomes must be an object")
    for genome, info in genomes.items():
        for kind, (_file_status, _optional) in kinds.items():
            value = (info or {}).get(kind, "")
            if value:
                rows.append((genome, kind, str(value)))
    return rows


def probe_path(path: Path, expected_kind: str) -> dict[str, str]:
    if not path.exists():
        return {"status": "missing", "note": "path not found"}
    if not path.is_file() and not path.is_dir():
        return {"status": "invalid", "note": "not a regular path"}
    if expected_kind == "directory":
        if not path.is_dir():
            return {"status": "invalid", "note": "expected a directory"}
    else:
        if not path.is_file():
            return {"status": "invalid", "note": "expected a file"}
        if path.stat().st_size == 0:
            return {"status": "empty", "note": "file is empty"}
    return {"status": "ok", "note": ""}


# Tool-path specifications: (tool key, config key, expectation).
# `auto_run_local` is read from the same tool block to decide whether a missing
# path is fatal: a tool the Agent will not run locally only needs to be listed
# so the user can run it themselves.
TOOL_PATH_SPECS: tuple[tuple[str, str, str], ...] = (
    ("sequence_screen", "executable", "program"),
    ("sequence_screen", "cdhit_executable", "program"),
    ("structure_prediction", "executable", "program"),
    ("usalign", "executable", "program"),
    ("deer", "executable", "program"),
    ("deer", "script_path", "file"),
    ("signalp", "executable", "program"),
)
FEDKEA_PATH_SPECS: tuple[tuple[str, str, str], ...] = (
    ("fedkea", "executable", "program"),
    ("fedkea", "script_path", "file"),
)
PLACEHOLDER_PREFIXES = ("/path/to", "path/to/", "yourlab.example.com")


def configured_tool_paths(project: dict[str, Any]) -> list[tuple[str, str, bool, str]]:
    """Yield (label, value, auto_run_local, expectation) for every configured tool path."""
    rows: list[tuple[str, str, bool, str]] = []
    tools = project.get("tools") or {}
    for tool, key, expected in TOOL_PATH_SPECS:
        block = tools.get(tool) or {}
        if not isinstance(block, dict):
            continue
        value = str(block.get(key, "") or "").strip()
        if not value:
            continue
        rows.append((f"tools.{tool}.{key}", value, bool(block.get("auto_run_local")), expected))
    fedkea = (project.get("validation_inputs") or {}).get("fedkea") or {}
    if isinstance(fedkea, dict):
        for tool, key, expected in FEDKEA_PATH_SPECS:
            value = str(fedkea.get(key, "") or "").strip()
            if not value:
                continue
            rows.append((f"validation_inputs.{tool}.{key}", value, bool(fedkea.get("auto_run_local")), expected))
    return rows


def probe_executable_path(value: str, expected: str = "program") -> tuple[str, str]:
    """Classify a configured tool path.

    Distinguishes an untouched example placeholder from a genuinely absent tool,
    because the fix differs: the first needs the user to supply a real path, the
    second needs the tool installed (or running elsewhere).
    """
    if not value:
        return "not_configured", "tool path is not configured"
    low = value.lower()
    if any(p in low for p in PLACEHOLDER_PREFIXES):
        return "placeholder", "still an example placeholder; replace it with the real path"
    path = Path(value).expanduser()
    if path.is_absolute() or os.sep in value:
        if path.exists():
            if expected == "file" and path.is_dir():
                return "invalid", "expected a file but found a directory"
            if not os.access(path, os.X_OK):
                return "invalid", "path exists but is not executable"
            return "ok", ""
        return "missing", "path not found"
    found = shutil.which(value)
    if found:
        return "ok", f"resolved on PATH -> {found}"
    return "missing", "not found on PATH"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preflight candidate microbial input paths from a project JSON."
    )
    parser.add_argument("--project", type=Path, help="Project JSON or project directory.")
    parser.add_argument("--report", type=Path, help="Optional TSV report path.")
    parser.add_argument(
        "--require-genome-complete",
        action="store_true",
        help="Treat optional .faa/.ffn/.fna/.gbff entries as fatal when missing or empty.",
    )
    parser.add_argument(
        "--require-target-sequence",
        action="store_true",
        help="Treat inputs.target_sequence_fasta as fatal when missing.",
    )
    parser.add_argument(
        "--require-target-structure",
        action="store_true",
        help="Treat target structure and catalytic-residue inputs as fatal when missing.",
    )
    parser.add_argument(
        "--require-tools",
        action="store_true",
        help=(
            "Also check the tools.* executable/script paths. A path is fatal when it is "
            "still an example placeholder (/path/to/...), or when it does not resolve AND "
            "the tool has auto_run_local enabled (meaning the Agent intends to run it)."
        ),
    )
    args = parser.parse_args(argv)

    project_path = args.project or Path.cwd() / "project.json"
    project, root = load_project(project_path)
    inputs = project.get("inputs") or {}
    checks: list[dict[str, str]] = []

    def add(kind: str, value: Any, expected: str, fatal: bool, absent_note: str) -> None:
        status = "not_configured"
        note = absent_note
        rendered = ""
        resolved = ""
        if value:
            rendered = str(value)
            resolved = resolve_path(rendered, root)
            probe = probe_path(resolved, expected)
            status = probe["status"]
            note = probe["note"]
            # Optional values are informative but do not stop a workflow.  In
            # particular a .gbff may be absent while a .faa is available.
            if not fatal and status != "ok":
                status = f"optional_{status}"
        checks.append(
            {
                "path": rendered,
                "kind": kind,
                "status": status,
                "note": note,
                "resolved_path": str(resolved),
            }
        )

    add(
        "target_sequence_fasta",
        inputs.get("target_sequence_fasta"),
        "file",
        bool(args.require_target_sequence),
        "target sequence is not configured; Agent may build it from EC/reaction/Literature or ask the user",
    )
    add(
        "target_structure_pdb",
        inputs.get("target_structure_pdb"),
        "file",
        bool(args.require_target_structure),
        "target structure is not configured; obtain or predict it before US-align",
    )
    add(
        "target_catalytic_residues_file",
        inputs.get("target_catalytic_residues_file"),
        "file",
        False,
        "catalytic-residue mapping is optional; DEER can still be used without it",
    )
    add(
        "candidate_proteome_fasta",
        inputs.get("candidate_proteome_fasta"),
        "file",
        bool(inputs.get("candidate_proteome_fasta")),
        "candidate proteome is not configured yet",
    )
    add(
        "candidate_annotation_fasta",
        inputs.get("candidate_annotation_fasta"),
        "file",
        False,
        "source .faa annotation is optional during preflight",
    )
    add(
        "candidate_annotation_gbff",
        inputs.get("candidate_annotation_gbff"),
        "file",
        False,
        "source .gbff annotation is optional during preflight",
    )

    genome_rows = configured_genome_inputs(project)
    for genome, kind, value in genome_rows:
        add(
            f"{genome}::{kind}",
            value,
            "directory" if kind.endswith("_dir") else "file",
            True,
            "optional genome input is not configured",
        )

    if args.require_tools:
        for label, value, auto_run, expected in configured_tool_paths(project):
            tool_status, tool_note = probe_executable_path(value, expected)
            fatal = tool_status in ("placeholder", "missing", "invalid")
            # A tool the Agent will not run locally is only informative.
            if fatal and not auto_run:
                fatal = False
            if tool_status != "ok" and not fatal:
                tool_status = f"optional_{tool_status}"
            checks.append(
                {
                    "path": str(value) if value else "",
                    "kind": label,
                    "status": tool_status,
                    "note": tool_note,
                    "resolved_path": str(value) if value else "",
                }
            )

    if args.report:
        report = args.report.expanduser()
        report = report if report.is_absolute() else root / report
        report.parent.mkdir(parents=True, exist_ok=True)
        with report.open("w", encoding="utf-8", newline="") as handle:
            handle.write("\t".join(FIELDS) + "\n")
            for check in checks:
                handle.write(
                    "\t".join(str(check[field]) for field in FIELDS) + "\n"
                )

    terminal_statuses = {"missing", "invalid", "empty", "placeholder"}
    fatal_rows = [
        row
        for row in checks
        if any(row["status"] == status for status in terminal_statuses)
    ]
    optional_rows = [row for row in checks if row["status"].startswith("optional_")]

    for row in checks:
        if row["status"] == "ok":
            print(f"[ok]            {row['kind']}: {row['resolved_path']}")
        elif row["status"] == "not_configured":
            print(f"[not configured] {row['kind']}: {row['note']}")
        elif row["status"].startswith("optional_"):
            short_status = row["status"].removeprefix("optional_")
            print(
                f"[optional {short_status:>7}] {row['kind']}: {row['path'] or row['note']} ({row['note']})"
            )
        else:
            print(f"[{row['status']:<15}] {row['kind']}: {row['path']} ({row['note']})")

    if args.report:
        print(f"wrote {report.resolve()}")

    if fatal_rows:
        print(
            f"\n{len(fatal_rows)} required/inconsistent candidate input(s) need correction.",
            file=sys.stderr,
        )
        return 1
    if not (
        bool(inputs.get("candidate_proteome_fasta"))
        or genome_rows
        or bool(inputs.get("candidate_annotation_fasta"))
        or bool(inputs.get("candidate_annotation_gbff"))
    ):
        print(
            "No candidate proteome or candidate genome files are configured.",
            file=sys.stderr,
        )
        return 1
    if optional_rows:
        print(
            f"\nPreflight passed with {len(optional_rows)} optional input(s) pending.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
