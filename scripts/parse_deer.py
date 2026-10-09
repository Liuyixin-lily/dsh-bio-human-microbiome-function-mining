#!/usr/bin/env python3
"""Parse DEER retrieval similarity.csv into plugin structural evidence tables.

DEER writes a sorted CSV of template/database pairs with a Euclidean distance.
Smaller distance means closer representation. This parser does not convert that
distance into a US-align TM-score; it keeps the raw DEER metric in a dedicated
field and marks structure_support according to the configured cutoff.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Any


def read_similarity(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters="\t,")
        except csv.Error:
            dialect = csv.excel_tab if "\t" in sample else csv.excel
        reader = csv.DictReader(handle, dialect=dialect)
        for row in reader:
            if not row or not any(row.values()):
                continue
            rows.append(
                {
                    "template_id": row.get("template_id", "").strip(),
                    "bacteria_id": row.get("bacteria_id", "").strip(),
                    "distance": row.get("distance", "").strip(),
                }
            )
    return rows


def clean_id(value: str) -> str:
    """Strip PDB path/extensions before reading candidate IDs from DEER."""
    value = value.strip()
    if not value:
        return value
    # DEER database identifiers sometimes carry a .pdb or .chain suffix.
    if value.lower().endswith((".pdb", ".cif")):
        value = value[:-4]
    if ":" in value and "." not in value.split(":", 1)[0]:
        # Foldseek chain-name-mode can produce "name:chain".
        value = value.split(":", 1)[0]
    return value


def build_id_to_genome(candidate_dir: Path, source_genomes: list[str]) -> dict[str, str]:
    """Map candidate structure id to source genome by reading symlink targets."""
    mapping: dict[str, str] = {}
    if not candidate_dir.is_dir():
        return mapping
    for path in candidate_dir.iterdir():
        if path.suffix.lower() not in (".pdb", ".cif"):
            continue
        try:
            target = Path(os.path.realpath(path))
        except OSError:
            continue
        parts = target.parts
        for genome in source_genomes:
            genome_name = Path(genome).name
            if any(part == genome_name or part.startswith(genome_name) for part in parts):
                mapping[path.stem] = genome_name
                break
    return mapping


def to_rows(similarity: list[dict[str, str]], args: argparse.Namespace) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    id_to_genome: dict[str, str] = {}
    source_genomes = [item.strip() for item in str(args.source_genomes or "").split(",") if item.strip()]
    if args.candidate_dir and source_genomes:
        id_to_genome = build_id_to_genome(args.candidate_dir, source_genomes)
    for rank, item in enumerate(similarity, start=1):
        candidate_id = clean_id(item.get("bacteria_id", ""))
        template_id = clean_id(item.get("template_id", ""))
        distance = item.get("distance", "")
        if not candidate_id:
            continue
        try:
            dist_float = float(distance)
            distance = f"{dist_float:.6f}"
        except (TypeError, ValueError):
            dist_float = float("inf")
        support = "1" if dist_float <= args.distance_cutoff else "0"
        deer_score = 1.0 / (1.0 + dist_float) if dist_float != float("inf") else 0.0
        organism = id_to_genome.get(candidate_id, args.organism)
        rows.append(
            {
                "candidate_id": candidate_id,
                "representative_id": candidate_id,
                "assembly_accession": args.assembly_accession,
                "protein_accession": candidate_id,
                "organism_or_strain": organism,
                "annotation": "",
                "template_id": template_id,
                "tm_score_1": "",
                "tm_score_2": "",
                "tm_score_mean": "",
                "rmsd": "",
                "aligned_length": "",
                "sequence_identity": "",
                "deer_distance": distance,
                "deer_rank": str(rank),
                "structure_support": support,
                "plddt_mean": "",
                "structural_score": f"{deer_score:.4f}" if support == "1" else "",
                "tool": args.tool,
                "tool_version": args.tool_version,
                "priority_tier": "",
                "prediction_pdb": candidate_id + ".pdb",
                "aligned_residues": "",
                "notes": f"parsed from {args.input.name}; smaller DEER distance is better",
            }
        )
    return rows


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse DEER similarity.csv into plugin structural evidence TSV."
    )
    parser.add_argument("--input", type=Path, required=True, help="DEER similarity.csv.")
    parser.add_argument("--output", type=Path, required=True, help="Output structural_candidates.tsv.")
    parser.add_argument("--assembly-accession", default="", help="Assembly accession for these DEER hits.")
    parser.add_argument("--organism", default="", help="Organism/strain label for these DEER hits.")
    parser.add_argument(
        "--candidate-dir",
        type=Path,
        help="Optional candidate structure directory with symlinks used to map ids back to source genomes.",
    )
    parser.add_argument(
        "--source-genomes",
        default="",
        help="Optional comma-separated source genome names used with --candidate-dir.",
    )
    parser.add_argument(
        "--distance-cutoff",
        type=float,
        default=12.0,
        help="DEER distance cutoff for structure_support=1, default 12.0.",
    )
    parser.add_argument("--tool", default="deer", help="Tool name, default: deer.")
    parser.add_argument("--tool-version", default="", help="DEER version or repository tag.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.input.is_file():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 2
    similarity = read_similarity(args.input)
    rows = to_rows(similarity, args)
    write_tsv(args.output, rows)
    print(f"wrote {args.output} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
