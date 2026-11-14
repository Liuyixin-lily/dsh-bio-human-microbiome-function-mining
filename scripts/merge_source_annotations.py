#!/usr/bin/env python3
"""Fill the `annotation` column of a candidate table from parsed source features.

The fast path (`SEQUENCE_ANNOTATION_CONFIRMED`) compares the candidate's own annotation with the
target activity. `parse_sequence_hits.py` cannot know the product names, because a protein FASTA
usually carries only accessions; the annotations live in the GenBank/GFF that came with the genome.
This step bridges the two, and it only fills blanks — a value already in the table is never replaced.

Usage:

    python3 scripts/merge_source_annotations.py \
        --candidates outputs/screening/sequence_candidates.tsv \
        --annotations outputs/screening/source_annotations.tsv \
        --output outputs/screening/sequence_candidates.annotated.tsv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ACCESSION_COLUMNS = ("protein_accession", "candidate_id", "locus_tag", "protein_id")
ANNOTATION_COLUMNS = ("product", "annotation", "description", "gene_product", "note")


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), list(reader)


def annotation_map(path: Path) -> dict[str, str]:
    fields, rows = read_rows(path)
    acc_col = next((c for c in ACCESSION_COLUMNS if c in fields), None)
    ann_col = next((c for c in ANNOTATION_COLUMNS if c in fields), None)
    if acc_col is None or ann_col is None:
        raise SystemExit(
            f"error: {path} needs an accession column ({'/'.join(ACCESSION_COLUMNS)}) and an "
            f"annotation column ({'/'.join(ANNOTATION_COLUMNS)}); found {fields}"
        )
    mapping: dict[str, str] = {}
    for row in rows:
        accession = (row.get(acc_col) or "").strip()
        annotation = (row.get(ann_col) or "").strip()
        if accession and annotation and accession not in mapping:
            mapping[accession] = annotation
    return mapping


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fill empty candidate annotations from parsed source features.",
    )
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    if not args.candidates.is_file():
        print(f"error: candidates not found: {args.candidates}", file=sys.stderr)
        return 2
    if not args.annotations.is_file():
        print(f"error: annotations not found: {args.annotations}", file=sys.stderr)
        return 2

    mapping = annotation_map(args.annotations)
    fields, rows = read_rows(args.candidates)
    if "annotation" not in fields:
        fields = fields + ["annotation"]
    filled = 0
    for row in rows:
        if (row.get("annotation") or "").strip():
            continue
        for column in ACCESSION_COLUMNS:
            value = (row.get(column) or "").strip()
            if value and value in mapping:
                row["annotation"] = mapping[value]
                filled += 1
                break
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
    print(
        f"annotated {filled} of {len(rows)} row(s) from {len(mapping)} source feature(s) -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
