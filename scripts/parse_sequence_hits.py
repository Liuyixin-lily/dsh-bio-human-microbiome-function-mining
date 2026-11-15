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
    # the template a candidate matched. Dropping it left every row saying only "a sequence hit"
    # with no way to tell which reference enzyme it resembled.
    "qseqid": "representative_id",
    "sseqid": "candidate_id",
    "pident": "pident",
    "length": "query_length",
    "evalue": "evalue",
    "bitscore": "bitscore",
    "qcovhsp": "query_coverage",
}


# DIAMOND `--outfmt 6 ...` writes NO header. Reading such a file with csv.DictReader
# consumes the first hit as the header column names, which silently deletes that hit —
# and reduces a one-hit result to zero rows. Positional names below match the outfmt the
# runner emits.
DIAMOND_FIELDS = [
    "qseqid", "sseqid", "pident", "length", "mismatch", "gapopen",
    "qstart", "qend", "sstart", "send", "evalue", "bitscore", "qcovhsp",
]
HEADER_HINTS = {"qseqid", "query_id", "sseqid", "candidate_id"}


def looks_like_header(first_line: list[str]) -> bool:
    if not first_line:
        return False
    if {cell.strip().lower() for cell in first_line} & HEADER_HINTS:
        return True
    # a header would carry words where the body carries numbers
    for index in (2, 3, 10, 11, 12):
        if index < len(first_line):
            try:
                float(first_line[index])
            except ValueError:
                return True
    return False


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
        first = sample.splitlines()[0].split("\t")
        if looks_like_header(first):
            for record in csv.DictReader(handle, delimiter="\t"):
                if record and any(record.values()):
                    rows.append(record)
            return rows
        # headerless DIAMOND output: name the columns by position, never drop a line.
        # A short layout (for example the 9-column one people type by hand) shifts every value after
        # `length`, so evalue/coverage/bitscore silently became empty strings and the fast path could
        # never fire. Refuse it instead of producing a table full of blanks.
        expected = len(DIAMOND_FIELDS)
        for line in handle:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            cells = line.split("\t")
            if len(cells) < expected:
                raise SystemExit(
                    f"error: {path} has {len(cells)} column(s), expected {expected} for DIAMOND "
                    "outfmt. Use: --outfmt 6 qseqid sseqid pident length mismatch gapopen qstart "
                    "qend sstart send evalue bitscore qcovhsp"
                )
            record = {
                field: (cells[index] if index < len(cells) else "")
                for index, field in enumerate(DIAMOND_FIELDS)
            }
            rows.append(record)
    return rows


def normalize_row(row: dict[str, str], args: argparse.Namespace) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for src, dst in READABLE_HEADERS.items():
        value = row.get(src, row.get(dst, "")).strip()
        if dst == "pident" or dst == "query_coverage":
            value = parse_float(value)
        out[dst] = value
    out["assembly_accession"] = (row.get("assembly_accession", "").strip()
                                or (args.assembly or "").strip())
    out["protein_accession"] = out["candidate_id"]
    out["organism_or_strain"] = (row.get("organism_or_strain", "").strip()
                                 or (args.organism or "").strip())
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
    parser.add_argument(
        "--organism",
        default="",
        help="Organism or strain the candidate proteome came from; fills a schema-required column "
             "that otherwise stays empty.",
    )
    parser.add_argument("--assembly", default="", help="Assembly accession for the candidate proteome.")
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
        "representative_id",
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

    # hits keeps every (template, candidate) pair; the candidate table keeps one row per candidate,
    # represented by its best alignment. Without this the same protein appeared once per matching
    # template and read as several candidates.
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row["candidate_id"]
        current = best.get(key)
        if current is None:
            best[key] = row
            continue
        try:
            better = (float(row.get("pident") or 0), float(row.get("bitscore") or 0)) > (
                float(current.get("pident") or 0), float(current.get("bitscore") or 0)
            )
        except ValueError:
            better = False
        if better:
            best[key] = row
    candidate_rows = list(best.values())
    write_tsv(args.out_hits, hits_fields, rows)
    write_tsv(args.out_candidates, candidate_fields, candidate_rows)
    print(f"wrote {args.out_hits} ({len(rows)} rows)")
    print(f"wrote {args.out_candidates} ({len(candidate_rows)} rows, one per candidate)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
