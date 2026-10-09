#!/usr/bin/env python3
"""Convert DIAMOND tabular output into plugin sequence hit tables.

The script wraps a single DIAMOND-style TSV into:
- sequence_hits.tsv: schema-compatible rows.
- sequence_candidates.tsv: same rows with an identity/coverage-derived score.

It never invents hits; a missing input file is an error.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any


READABLE_HEADERS = {
    "qseqid": "query_id",
    "sseqid": "candidate_id",
    "pident": "pident",
    "length": "query_length",
    "evalue": "evalue",
    "bitscore": "bitscore",
    "qcovhsp": "query_coverage",
}


def detect_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        if not sample.strip():
            return rows
        if "\t" not in sample:
            print(f"error: not a tab-separated file: {path}", file=sys.stderr)
            sys.exit(2)
        reader = csv.DictReader(handle, delimiter="\t")
        for record in reader:
            if not record or not any(record.values()):
                continue
            rows.append(record)
    return rows


def normalize_row(row: dict[str, str], args: argparse.Namespace) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for src, dst in READABLE_HEADERS.items():
        value = row.get(src, row.get(dst, "")).strip()
        if dst == "pident" or dst == "query_coverage":
            value = parse_float(value)
        out[dst] = value
    out["assembly_accession"] = row.get("assembly_accession", "").strip()
    out["protein_accession"] = out["candidate_id"]
    out["organism_or_strain"] = row.get("organism_or_strain", "").strip()
    out["annotation"] = row.get("annotation", "").strip()
    out["evidence_class"] = row.get("evidence_class", args.evidence_class).strip()
    out["tool"] = args.tool
    out["tool_version"] = args.tool_version
    out["notes"] = ""
    return out


def parse_float(value: str) -> Any:
    try:
        return float(value)
    except ValueError:
        return ""


def identity_score(row: dict[str, Any], args: argparse.Namespace) -> str:
    identity = row.get("pident", "")
    coverage = row.get("query_coverage", "")
    if identity == "" or coverage == "":
        return ""
    try:
        score = float(identity) * float(coverage)
        return f"{score:.3f}"
    except (TypeError, ValueError):
        return ""


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a DIAMOND TSV into plugin sequence tables."
    )
    parser.add_argument("--input", type=Path, required=True, help="Input TSV with DIAMOND-style columns.")
    parser.add_argument("--out-hits", type=Path, required=True, help="Output sequence_hits.tsv.")
    parser.add_argument("--out-candidates", type=Path, required=True, help="Output sequence_candidates.tsv.")
    parser.add_argument("--tool", default="diamond", help="Tool name, default: diamond.")
    parser.add_argument("--tool-version", default="", help="Tool version.")
    parser.add_argument(
        "--evidence-class",
        default="sequence_supported",
        choices=["known", "ambiguous", "unknown", "weak", "sequence_supported"],
        help="Evidence class to assign when not present in the input.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.input.is_file():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 2

    rows = [normalize_row(row, args) for row in detect_rows(args.input)]
    for row in rows:
        row["sequence_score"] = identity_score(row, args)
        row["priority_tier"] = ""

    hits_fields = [
        "candidate_id",
        "protein_accession",
        "assembly_accession",
        "organism_or_strain",
        "annotation",
        "evidence_class",
        "pident",
        "query_coverage",
        "evalue",
        "bitscore",
        "tool",
        "tool_version",
    ]
    candidate_fields = hits_fields + ["sequence_score", "priority_tier"]
    write_tsv(args.out_hits, hits_fields, rows)
    write_tsv(args.out_candidates, candidate_fields, rows)
    print(f"wrote {args.out_hits} ({len(rows)} rows)")
    print(f"wrote {args.out_candidates} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
