#!/usr/bin/env python3
"""Merge sequence, structural, FedKEA, and existing source annotations into one ranked table.

The output follows schemas/combined_candidates.schema.tsv. Every row must carry
at least a candidate_id and provenance. Unknown fields are left empty instead of
being fabricated.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any


COMBINED_FIELDS = [
    "candidate_id",
    "representative_id",
    "assembly_accession",
    "protein_accession",
    "organism_or_strain",
    "annotation",
    "evidence_class",
    "structure_support",
    "tm_score_mean",
    "sequence_score",
    "structural_score",
    "sequence_rank",
    "structural_rank",
    "catalytic_score",
    "genome_context_score",
    "ecological_score",
    "overall_score",
    "priority_tier",
    "provenance",
    "notes",
    "fedkea_binary_result_file",
    "fedkea_is_enzyme",
    "fedkea_enzyme_probability",
    "fedkea_ec_confidence_file",
    "fedkea_accepted_name",
    "fedkea_other_names",
    "fedkea_final_result",
    "fedkea_tool_version",
    "fedkea_notes",
    "fedkea_ec_confidence",
    "fedkea_additional_scores",
    "pident",
    "query_coverage",
    "evalue",
    "bitscore",
    "predicted_function",
    "experimental_knowledge",
    "evidence_class_definition",
    "fedkea_raw_ec_list",
    "fedkea_first",
    "fedkea_first_probability",
    "fedkea_second",
    "fedkea_second_probability",
    "fedkea_third",
    "fedkea_third_probability",
    "fedkea_fourth",
    "fedkea_fourth_probability",
    "existing_annotation",
    "source_product",
    "source_protein_name",
    "source_gene",
    "source_locus_tag",
    "source_ec_number",
    "source_pfam",
    "source_interpro",
    "source_tigrfam",
    "source_cazy",
    "source_kegg_orthology",
    "source_cog",
    "source_go_terms",
    "source_description",
    "source_feature_annotation_source",
    "source_annotation_note",
    "deer_distance",
    "deer_rank",
]


def read_tsv(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not path.is_file():
        return rows
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row and any(row.values()):
                rows.append(row)
    return rows


def max_existing(*values: str) -> str:
    numeric: list[float] = []
    for value in values:
        try:
            numeric.append(float(value))
        except (TypeError, ValueError):
            continue
    if not numeric:
        return ""
    return f"{max(numeric):.4f}"


def read_project_candidate_map(path: str | None) -> dict[str, dict[str, str]]:
    """Read optional project JSON candidate metadata keyed by protein accession.

    The demo project format stores candidate-level source genome paths in
    `candidate_sequences`. If present, the merge uses it only to fill fields
    that are still empty, never to overwrite parsed evidence.
    """
    if not path:
        return {}
    project = json.loads(Path(path).read_text(encoding="utf-8"))
    candidate_map: dict[str, dict[str, str]] = {}
    genomes = (project.get("candidate_sequences") or {}).get("genomes") or {}
    candidates = (project.get("candidate_sequences") or {}).get("candidates") or {}
    for accession, info in candidates.items():
        organism = info.get("source_genome", "")
        assembly = info.get("assembly_accession", "")
        if not assembly:
            for key in ("protein_fasta", "cds_fasta", "gbff"):
                candidate_path = info.get(key) or (genomes.get(organism) or {}).get(key, "")
                assembly = extract_assembly_accession(candidate_path)
                if assembly:
                    break
        candidate_map[accession.strip()] = {
            "organism_or_strain": organism,
            "assembly_accession": assembly,
        }
    return candidate_map


def extract_assembly_accession(path: str) -> str:
    match = re.search(r"(GCF|GCA)_\d+\.\d+", path or "")
    return match.group(0) if match else ""


def merge_candidates(
    sequence_rows: list[dict[str, str]],
    structural_rows_list: list[list[dict[str, str]]],
    fedkea_rows: list[dict[str, str]],
    source_annotation_rows: list[dict[str, str]],
    deer_organisms: list[str] | None = None,
    project_map: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    by_accession: dict[str, dict[str, str]] = {}
    order: list[str] = []

    def upsert(accession: str) -> dict[str, str]:
        if accession not in by_accession:
            by_accession[accession] = {}
            order.append(accession)
        return by_accession[accession]

    candidate_to_protein: dict[str, str] = {}

    for row in sequence_rows:
        accession = row.get("protein_accession", row.get("candidate_id", "")).strip()
        if not accession:
            continue
        candidate_to_protein[row.get("candidate_id", "").strip()] = accession
        merged = upsert(accession)
        for key, value in row.items():
            merged.setdefault(key, value)
            merged["provenance"] = "sequence_hits;sequence_candidates"

    deer_organisms = [org.strip() for org in (deer_organisms or []) if org.strip()]
    for structural_rows in structural_rows_list:
        if not structural_rows:
            continue
        is_deer = any(
            row.get("structure_support") in ("deer", "DEER")
            or row.get("deer_distance")
            or row.get("deer_rank")
            for row in structural_rows
            if isinstance(row, dict)
        )
        provenance_tag = "structural_hits;structural_candidates"
        if is_deer:
            provenance_tag = "structural_hits;structural_candidates;deer_results"
        for row in structural_rows:
            if not isinstance(row, dict):
                continue
            if is_deer and deer_organisms:
                organism = (row.get("organism_or_strain") or "").strip()
                if organism and not any(organism == org or organism.startswith(org) for org in deer_organisms):
                    continue
            # Structural rows are keyed by the sequence candidate protein
            # accession.  When the structural row only carries candidate_id,
            # resolve that candidate id through the sequence candidates table.
            protein_accession = row.get("protein_accession", "").strip()
            if not protein_accession:
                candidate_id = row.get("candidate_id", "").strip()
                protein_accession = candidate_to_protein.get(candidate_id, candidate_id)
            if not protein_accession:
                continue
            row = dict(row)
            row["protein_accession"] = protein_accession
            merged = upsert(protein_accession)
            for key, value in row.items():
                if not value:
                    continue
                merged.setdefault(key, value)
            # Prefer US-align (TM-score) over DEER (distance-derived) when both
            # describe the same candidate, so submit/structure-first scoring is
            # not driven by lower-quality DEER support.
            incoming_has_usalign = bool(row.get("tm_score_mean") or row.get("tool", "").strip().lower() == "usalign")
            if incoming_has_usalign:
                merged["structure_support"] = row.get("structure_support", "1")
                merged["tm_score_mean"] = max_existing(
                    merged.get("tm_score_mean", ""), row.get("tm_score_mean", "")
                )
                merged["structural_score"] = row.get("structural_score", row.get("tm_score_mean", ""))
            elif not merged.get("tm_score_mean"):
                merged["structure_support"] = row.get("structure_support", "1")
                merged["structural_score"] = row.get("structural_score", row.get("tm_score_mean", ""))
            merged["provenance"] = ";".join(
                part for part in [merged.get("provenance", ""), provenance_tag] if part
            )

    for row in fedkea_rows:
        accession = row.get("protein_accession", "").strip()
        if not accession:
            continue
        merged = upsert(accession)
        for key, value in row.items():
            if key == "protein_accession":
                continue
            merged[key] = value
        merged["provenance"] = ";".join(
            part for part in [merged.get("provenance", ""), "fedkea_results"] if part
        )

    for row in source_annotation_rows:
        accession = row.get("protein_accession", "").strip()
        if not accession:
            candidate_id = row.get("candidate_id", "").strip()
            accession = candidate_to_protein.get(candidate_id, "")
        if not accession or accession not in by_accession:
            continue
        merged = upsert(accession)
        source_fields = {
            "existing_annotation": row.get("description", row.get("product", "")),
            "source_product": row.get("product", ""),
            "source_protein_name": row.get("protein_name", ""),
            "source_gene": row.get("gene", ""),
            "source_locus_tag": row.get("locus_tag", ""),
            "source_ec_number": row.get("ec_number", ""),
            "source_pfam": row.get("pfam", ""),
            "source_interpro": row.get("interpro", ""),
            "source_tigrfam": row.get("tigrfam", ""),
            "source_cazy": row.get("cazy", ""),
            "source_kegg_orthology": row.get("kegg_orthology", ""),
            "source_cog": row.get("cog", ""),
            "source_go_terms": row.get("go_terms", ""),
            "source_description": row.get("description", ""),
            "source_feature_annotation_source": row.get("annotation_source", ""),
            "source_annotation_note": f"{row.get('source_file', '')} feature_type={row.get('feature_type','')}",
        }
        for key, value in source_fields.items():
            if not value:
                continue
            if key in ("source_product", "source_description", "source_ec_number"):
                merged.setdefault(key, value)
            else:
                merged[key] = value
        merged["provenance"] = ";".join(
            part for part in [merged.get("provenance", ""), "source_feature_annotations"] if part
        )

    rows: list[dict[str, str]] = []
    for accession in order:
        merged = by_accession[accession]
        merged.setdefault("candidate_id", accession)
        merged.setdefault("representative_id", accession)
        merged.setdefault("protein_accession", accession)
        if not merged.get("annotation", "").strip():
            existing = (merged.get("source_description") or merged.get("existing_annotation") or "").strip()
            if existing:
                merged["annotation"] = existing
        if not merged.get("evidence_class", "").strip():
            if merged.get("structural_score", "").strip():
                if (merged.get("deer_distance") or "").strip() or (merged.get("deer_rank") or "").strip():
                    merged["evidence_class"] = "deer_supported"
                else:
                    merged["evidence_class"] = "structure_supported"
            elif merged.get("sequence_score", "").strip():
                merged["evidence_class"] = "sequence_supported"
            elif merged.get("existing_annotation", "").strip():
                merged["evidence_class"] = "annotation_supported"
        if project_map:
            meta = project_map.get(accession, {})
            for field in ("organism_or_strain", "assembly_accession"):
                if not merged.get(field, "").strip() and meta.get(field, "").strip():
                    merged[field] = meta[field]
        rows.append(merged)

    ranked_sequence = [
        row for row in rows if (row.get("sequence_score") or "").strip() != ""
    ]
    ranked_sequence.sort(
        key=lambda row: float(row["sequence_score"]),
        reverse=True,
    )
    for rank, row in enumerate(ranked_sequence, start=1):
        row["sequence_rank"] = str(rank)

    ranked_structural = [
        row for row in rows if (row.get("structural_score") or "").strip() != ""
    ]
    ranked_structural.sort(
        key=lambda row: float(row["structural_score"]),
        reverse=True,
    )
    for rank, row in enumerate(ranked_structural, start=1):
        row["structural_rank"] = str(rank)

    return rows


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge candidate evidence into combined_candidates.tsv.")
    parser.add_argument("--sequence", type=Path, help="sequence_candidates.tsv.")
    parser.add_argument(
        "--structural",
        type=Path,
        action="append",
        help="structural_candidates.tsv. May be repeated for US-align and DEER runs.",
    )
    parser.add_argument(
        "--deer-organisms",
        default="",
        help="Comma-separated organisms for which DEER structural tables are valid. DEER hits from other organisms are ignored when merging.",
    )
    parser.add_argument("--fedkea", type=Path, help="parsed fedkea_results.tsv.")
    parser.add_argument("--source-annotations", type=Path, help="parsed source_feature_annotations.tsv.")
    parser.add_argument("--project", type=Path, help="Project JSON with optional candidate_sequences metadata.")
    parser.add_argument("--output", type=Path, required=True, help="Output combined_candidates.tsv.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.sequence and not args.structural and not args.fedkea and not args.source_annotations:
        print("error: provide at least one evidence table", file=sys.stderr)
        return 2
    rows = merge_candidates(
        read_tsv(args.sequence) if args.sequence else [],
        [read_tsv(path) for path in (args.structural or [])],
        read_tsv(args.fedkea) if args.fedkea else [],
        read_tsv(args.source_annotations) if args.source_annotations else [],
        deer_organisms=args.deer_organisms.split(","),
        project_map=read_project_candidate_map(str(args.project) if args.project else None),
    )
    write_tsv(args.output, COMBINED_FIELDS, rows)
    if rows:
        print(f"wrote {args.output} ({len(rows)} rows)")
    else:
        print(f"wrote {args.output} (0 rows: no candidate evidence passed thresholds)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
