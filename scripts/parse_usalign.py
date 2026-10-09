#!/usr/bin/env python3
"""Parse USalign -outfmt 2 text into structural hit and candidate tables."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any


def split_align_block(text: str) -> list[tuple[str, list[str]]]:
    """Extract per-alignment blocks from USalign -outfmt 2 stdout."""
    lines = [line.rstrip() for line in text.splitlines()]
    blocks: list[tuple[str, list[str]]] = []
    current: list[str] = []
    current_key = ""
    for line in lines:
        if "Template Name:" in line:
            if current:
                blocks.append((current_key, current))
            key = line.split(":", 1)[1].strip()
            current_key = key
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append((current_key, current))
    return blocks


def parse_tmscores(lines: list[str]) -> dict[str, str]:
    scores: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        for metric in ("TM-score", "RMSD", "IDen", "Aligned_length", "Seq_identity"):
            if metric in stripped:
                parts = stripped.split()
                if parts:
                    value = parts[-1]
                    key = metric.lower().replace("tm-score", "tm_score").replace("-", "")
                    scores[key] = value
    return scores


def chain_metadata(value: str) -> tuple[str, str]:
    """Return a stable structure id and source path from a PDBchain cell."""
    source = value.split(":", 1)[0]
    name = Path(source).name
    if "." in name:
        name = name.rsplit(".", 1)[0]
    return name, source


def rows_from_compact_table(text: str, args: argparse.Namespace) -> list[dict[str, Any]]:
    """Parse compact table output emitted by US-align ``-outfmt 2``."""
    fields: list[str] | None = None
    renamed_fields = {
        "PDBchain1": "target_chain",
        "PDBchain2": "candidate_chain",
        "TM1": "tm_score_1",
        "TM2": "tm_score_2",
        "ID1": "id1",
        "ID2": "id2",
        "IDali": "id_aligned",
        "L1": "length_1",
        "L2": "length_2",
        "Lali": "aligned_length",
    }
    rows: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#PDBchain1"):
            raw_fields = line.lstrip("#").split("\t")
            fields = [renamed_fields.get(field, field) for field in raw_fields]
            continue
        if fields is None:
            continue
        values = line.split("\t")
        if len(values) < 11:
            continue
        row = dict(zip(fields, values[: len(fields)]))
        candidate_id, candidate_source = chain_metadata(row["candidate_chain"])
        target_id, _ = chain_metadata(row["target_chain"])
        if not candidate_source and args.candidate_id:
            candidate_source = args.candidate_id
        if not target_id and args.template_id:
            target_id = args.template_id
        try:
            tm_1 = float(row["tm_score_1"])
            tm_2 = float(row["tm_score_2"])
            tm_mean = (tm_1 + tm_2) / 2.0
        except (KeyError, TypeError, ValueError):
            tm_1 = tm_2 = tm_mean = 0.0
        rows.append(
            {
                "candidate_id": candidate_id or args.candidate_id,
                "template_id": target_id or args.template_id,
                "tm_score_1": f"{tm_1:.4f}",
                "tm_score_2": f"{tm_2:.4f}",
                "tm_score_mean": f"{tm_mean:.4f}",
                "rmsd": row.get("rmsd", ""),
                "aligned_length": row.get("aligned_length", ""),
                "sequence_identity": row.get("id1", ""),
                "plddt_mean": args.plddt_mean,
                "tool": args.tool,
                "tool_version": args.tool_version,
                "structure_support": "1" if tm_mean >= args.threshold else "0",
                "prediction_pdb": candidate_source or args.prediction_pdb,
                "aligned_residues": "",
                "notes": f"parsed from {args.input.name}",
            }
        )
    return rows


def rows_from_text(path: Path, args: argparse.Namespace) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if "#PDBchain1" in text:
        return rows_from_compact_table(text, args)
    rows: list[dict[str, Any]] = []
    for key, lines in split_align_block(text):
        scores = parse_tmscores(lines)
        rows.append(
            {
                "candidate_id": args.candidate_id,
                "template_id": key,
                "tm_score_1": scores.get("tm_score", ""),
                "tm_score_2": scores.get("tm_score", ""),
                "tm_score_mean": scores.get("tm_score", ""),
                "rmsd": scores.get("rmsd", ""),
                "aligned_length": scores.get("aligned_length", ""),
                "sequence_identity": scores.get("seq_identity", ""),
                "plddt_mean": args.plddt_mean,
                "tool": args.tool,
                "tool_version": args.tool_version,
                "structure_support": "1" if float_or_zero(scores.get("tm_score", "")) >= args.threshold else "0",
                "prediction_pdb": args.prediction_pdb,
                "aligned_residues": "",
                "notes": f"parsed from {path.name}",
            }
        )
    return rows


def float_or_zero(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return 0.0


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse USalign -outfmt 2 output into TSV.")
    parser.add_argument("--input", type=Path, required=True, help="USalign -outfmt 2 stdout file.")
    parser.add_argument("--out-hits", type=Path, required=True, help="Output structural_hits.tsv.")
    parser.add_argument("--out-candidates", type=Path, required=True, help="Output structural_candidates.tsv.")
    parser.add_argument("--candidate-id", default="candidate", help="Candidate id prefix for parsed rows.")
    parser.add_argument("--template-id", default="template", help="Fallback template id when not detected.")
    parser.add_argument("--plddt-mean", default="", help="Mean pLDDT when known.")
    parser.add_argument("--prediction-pdb", default="", help="Path to predicted structure.")
    parser.add_argument("--tool", default="USalign", help="Tool name.")
    parser.add_argument("--tool-version", default="", help="Tool version.")
    parser.add_argument("--threshold", type=float, default=0.5, help="TM-score threshold, default 0.5.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.input.is_file():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 2
    rows = rows_from_text(args.input, args)
    hits_fields = [
        "candidate_id",
        "template_id",
        "tm_score_1",
        "tm_score_2",
        "tm_score_mean",
        "rmsd",
        "aligned_length",
        "sequence_identity",
        "plddt_mean",
        "tool",
        "tool_version",
        "structure_support",
        "prediction_pdb",
        "aligned_residues",
        "notes",
    ]
    candidate_fields = hits_fields + [
        "assembly_accession",
        "protein_accession",
        "organism_or_strain",
        "annotation",
        "structural_score",
        "priority_tier",
    ]
    for row in rows:
        row["assembly_accession"] = ""
        row["protein_accession"] = ""
        row["organism_or_strain"] = ""
        row["annotation"] = ""
        row["structural_score"] = row["tm_score_mean"]
        row["priority_tier"] = ""
    candidates = [row for row in rows if row.get("structure_support", "") in ("1", "true", "yes")]
    write_tsv(args.out_hits, hits_fields, rows)
    write_tsv(args.out_candidates, candidate_fields, candidates)
    print(f"wrote {args.out_hits} ({len(rows)} rows)")
    print(f"wrote {args.out_candidates} ({len(candidates)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
