#!/usr/bin/env python3
"""Validate plugin output TSVs against schema TSVs or JSON schemas.

Schemas stored in `schemas/` describe evidence-table contracts. For TSV schema
files, the top section lists required columns and the `# Optional but
recommended` section lists recommended columns. For JSON schemas, all
declared columns are treated as required unless specified otherwise.

By default this checker verifies header presence only: every required schema
column must exist in the output table. Empty cells on individual rows are
reported as warnings, not hard failures, so partial demo outputs can validate
while still showing which candidate-level fields are incomplete.

Use --require-nonempty to make empty required cells hard errors.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


def read_schema(path: Path) -> tuple[list[str], list[str]]:
    """Read a schema TSV and return (required_columns, recommended_columns).

    The first non-comment section is required. A comment header beginning with
    `# Optional` switches the parser to recommended columns. Anything after
    `# Notes` is prose and is ignored.
    """
    required: list[str] = []
    recommended: list[str] = []
    section: str = "required"
    in_notes = False
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        for raw in reader:
            row = raw
            if not row or not row[0]:
                continue
            line = row[0].strip()
            if not line:
                continue
            lowered = line.lower()
            if line.startswith("# Optional") or line.startswith("# optional"):
                section = "optional"
                continue
            if line.startswith("# Notes") or line.startswith("# notes"):
                in_notes = True
                continue
            if line.startswith("#") or in_notes:
                if in_notes:
                    break
                continue
            first = line.split("\t", 1)[0].strip()
            if not first:
                continue
            # Column names should look like snake_case without surrounding whitespace.
            if any(ch.isspace() for ch in first):
                continue
            if first.startswith(("-", "*", "`")):
                continue
            if section == "required":
                required.append(first)
            else:
                recommended.append(first)
    return list(dict.fromkeys(required)), list(dict.fromkeys(recommended))


def read_json_schema(path: Path) -> tuple[list[str], list[str]]:
    """Read schema/schema.json files that use properties/required objects."""
    data = json.loads(path.read_text(encoding="utf-8"))
    required = list(data.get("required", []) or [])
    props = list(data.get("properties", {}).keys())
    recommended = [col for col in props if col not in required]
    return required, recommended


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        headers = list(reader.fieldnames or [])
        rows = [row for row in reader if row and any(row.values())]
    return headers, rows


def validate(path: Path, schema_path: Path, require_nonempty: bool = False) -> list[dict[str, str]]:
    """Validate one output TSV against one schema.

    Returns a list of message dicts with `level` and `message` keys.
    """
    issues: list[dict[str, str]] = []
    if schema_path.suffix == ".json":
        required_columns, recommended_columns = read_json_schema(schema_path)
    else:
        required_columns, recommended_columns = read_schema(schema_path)

    if not required_columns and not recommended_columns:
        issues.append({"level": "error", "message": f"schema {schema_path} has no column declarations"})
        return issues

    headers, rows = read_tsv(path)
    if not headers:
        issues.append({"level": "error", "message": f"{path} is empty or has no header"})
        return issues

    missing_required = [col for col in required_columns if col not in headers]
    if missing_required:
        issues.append({"level": "error", "message": f"{path} missing required schema columns: {', '.join(missing_required)}"})

    missing_recommended = [col for col in recommended_columns if col not in headers]
    if missing_recommended:
        issues.append({"level": "warning", "message": f"{path} missing recommended schema columns: {', '.join(missing_recommended)}"})

    # Header-only schema validation stops here.
    checked = [col for col in required_columns if col in headers]
    if not checked:
        return issues

    for col in checked:
        empty = [i for i, row in enumerate(rows, 1) if not row.get(col, "").strip()]
        if not empty:
            continue
        suffix = ", ".join(str(i) for i in empty[:10]) + ("..." if len(empty) > 10 else "")
        if require_nonempty:
            issues.append({"level": "error", "message": f"{path} column '{col}' is empty on row(s): {suffix}"})
        else:
            issues.append({"level": "warning", "message": f"{path} required column '{col}' is empty on row(s): {suffix}"})
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", nargs="+", help="Schema path(s).")
    parser.add_argument("--tsv", nargs="+", help="Output TSV path(s).")
    parser.add_argument("--root", type=Path, default=Path("."), help="Plugin root; default '.'.")
    parser.add_argument("--require-nonempty", action="store_true", help="Treat empty required cells as hard errors.")
    args = parser.parse_args(argv)

    pairs: list[tuple[Path, Path]] = []
    if args.schema and args.tsv:
        if len(args.schema) != len(args.tsv):
            print("error: --schema and --tsv must have the same length", file=sys.stderr)
            return 2
        pairs = list(zip(args.schema, args.tsv))
    elif args.schema or args.tsv:
        print("error: provide both --schema and --tsv, or neither", file=sys.stderr)
        return 2
    else:
        default_map = {
            "outputs/task/combined_candidates.tsv": "schemas/combined_candidates.schema.tsv",
            "outputs/task/combined_candidates_full.tsv": "schemas/combined_candidates.schema.tsv",
            "outputs/sequence_screening/sequence_candidates.tsv": "schemas/sequence_candidates.schema.tsv",
            "outputs/sequence_screening/sequence_hits.tsv": "schemas/sequence_hits.schema.tsv",
            "outputs/alignments/run_full_085/structural_candidates.tsv": "schemas/structural_candidates.schema.tsv",
            "outputs/alignments/run_full_085/structural_hits.tsv": "schemas/structural_hits.schema.tsv",
            "outputs/source_feature_annotations.tsv": "schemas/source_feature_annotations.schema.tsv",
            "demo/outputs/task/combined_candidates_full.tsv": "schemas/combined_candidates.schema.tsv",
        }
        for output_rel, schema_rel in default_map.items():
            output = args.root / output_rel
            schema = args.root / schema_rel
            if output.is_file() and schema.is_file():
                pairs.append((output, schema))

    if not pairs:
        print("No files to validate. Provide --schema/--tsv pairs or run from a plugin/demo root with outputs.")
        return 1

    all_errors: list[dict[str, str]] = []
    for tsv, schema in pairs:
        tsv = Path(tsv)
        schema = Path(schema)
        all_errors.extend(validate(tsv, schema, require_nonempty=args.require_nonempty))

    errors = [issue for issue in all_errors if issue["level"] == "error"]
    warnings = [issue for issue in all_errors if issue["level"] == "warning"]

    if errors:
        print("Validation errors:")
        for issue in errors:
            print("- " + issue["message"])
    if warnings:
        print("Warnings:")
        for issue in warnings:
            print("- " + issue["message"])
    if not errors:
        print(f"Validated {len(pairs)} TSV file(s) against schema(s) with {len(warnings)} warning(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
