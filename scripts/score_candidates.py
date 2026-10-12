#!/usr/bin/env python3
"""Rank combined candidates with explicit, deterministic rules.

The ranking is intentionally not a black-box weighted sum. Every row is
assigned a `priority_tier` and a `priority_rule` from the rules below.

Default sort (`--rank-by structure`): structural similarity (TM-score) is the
primary key. Rows carrying a TM-score are ordered by it descending; rows with no
TM-score - fast-path rows that skipped structure, DEER rows that carry only a
distance, sequence-only and annotation-only rows - follow, ordered among
themselves by `priority_order`. Ties then break by sequence score, annotation
strength, and a stable identifier. `--rank-by priority` restores the earlier
tier-first ordering, where `priority_order` is primary and the structural score
only breaks ties.

Note on the two modes: `--rank-by structure` deliberately does NOT let a
`priority_rule` tier outrank a better structural match. That matters for
convergent / moonlighting targets, where the validated enzyme typically carries
an annotation and a FedKEA EC that differ from the target EC, so a tier-first
ordering demotes it below candidates whose EC merely happens to match.

Priority rules:

1. SEQUENCE_ANNOTATION_CONFIRMED: DIAMOND sequence hit with positive
   `sequence_score` and existing source annotation that matches the configured
   target EC or target enzyme name/product synonym. Structure screening is
   skipped for these rows.
2. USALIGN_TARGET_EC: US-align evidence meets the TM-score threshold and
   FedKEA assigns the configured target EC.
3. DEER_FEDKEA_CONFIRMED: DEER evidence was used because US-align did not
   leave enough suitable candidates, and FedKEA confirms the candidate as an
   enzyme. Above US-align evidence that arrived at a non-target EC.
4. USALIGN_OTHER_EC: US-align evidence meets the threshold and FedKEA assigns
   a different EC number.
5. USALIGN_NOT_ENZYME: US-align evidence meets the threshold and FedKEA
   predicts the candidate is not an enzyme.
6. USALIGN_UNVALIDATED: US-align evidence meets the threshold, but no FedKEA
   result has been provided yet.
7. DEER_FALLBACK: DEER evidence was used because US-align did not leave enough
   suitable candidates, and FedKEA has not confirmed enzyme function.
8. SEQUENCE_ONLY: sequence evidence only, no structure evidence.
9. ANNOTATION_ONLY: only existing source annotations are available.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any


# Every column this script sets must be guaranteed present in the output header,
# otherwise write_tsv silently drops it. overall_score and priority_tier are
# required columns of combined_candidates.schema.tsv, so losing them breaks the
# schema contract.
OUTPUT_FIELDS = (
    "overall_rank",
    "overall_score",
    "rank_policy",
    "priority_order",
    "priority_rule",
    "priority_tier",
    "sequence_rank",
    "structural_rank",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assign explicit priority overall_rank, overall_score, and priority_tier."
    )
    parser.add_argument("--input", type=Path, required=True, help="combined_candidates.tsv.")
    parser.add_argument(
        "--output",
        type=Path,
        help="Scored output TSV. Defaults to overwriting --input.",
    )
    parser.add_argument(
        "--tm-threshold",
        type=float,
        default=0.5,
        help="TM-score threshold for US-align priority rules, default 0.5.",
    )
    parser.add_argument(
        "--target-ec",
        default="",
        help="Comma-separated target EC numbers used to identify FedKEA target matches.",
    )
    parser.add_argument(
        "--target-name",
        default="",
        help="Comma-separated target enzyme names/synonyms used by the "
        "sequence+annotation fast path to detect matching existing source annotations.",
    )
    parser.add_argument(
        "--policy",
        default=None,
        help=(
            "Label recorded in rank_policy. Defaults to a label derived from "
            "--rank-by: structure_first_tm_score for 'structure', "
            "priority_rule_first for 'priority'."
        ),
    )
    parser.add_argument(
        "--rank-by",
        choices=("structure", "priority"),
        default="structure",
        help=(
            "Primary sort key. 'structure' (default) ranks by structural similarity "
            "(TM-score) descending: rows carrying a TM-score come first, and rows with "
            "no TM-score (fast-path rows that skipped structure, DEER rows, "
            "sequence-only, annotation-only) follow, ordered among themselves by "
            "priority_order. 'priority' restores the earlier behaviour where the "
            "priority_rule tier is the primary key."
        ),
    )
    parser.add_argument(
        "--no-sort",
        action="store_true",
        help="Write scores and tiers without reordering rows.",
    )
    return parser.parse_args(argv)


def read_tsv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader if row and any(row.values())]
    return rows, fields


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def numeric(value: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return result


def structural_component(row: dict[str, str]) -> float:
    for field in ("structural_score", "tm_score_mean"):
        value = numeric(row.get(field, ""))
        if value == value and value != 0:
            return max(0.0, min(value, 1.0)) if value <= 1.0 else min(value / 2.0, 1.0)
    return 0.0


def sequence_component(row: dict[str, str], max_sequence_score: float) -> float:
    sequence_score = numeric(row.get("sequence_score", ""))
    if sequence_score != sequence_score:
        return 0.0
    if sequence_score <= 0:
        return 0.0
    if sequence_score <= 1.0:
        return sequence_score
    if max_sequence_score <= 0:
        return 0.0
    return min(sequence_score / max_sequence_score, 1.0)


def annotation_component(row: dict[str, str]) -> float:
    score = 0.0
    if row.get("source_ec_number", "").strip():
        score += 0.5
    domain_fields = [
        "source_pfam",
        "source_interpro",
        "source_tigrfam",
        "source_cazy",
        "source_kegg_orthology",
    ]
    if any(row.get(field, "").strip() for field in domain_fields):
        score += 0.3
    if row.get("source_product", "").strip() or row.get("existing_annotation", "").strip():
        score += 0.2
    if row.get("fedkea_is_enzyme", "").strip().lower() in ("1", "true", "yes"):
        score += 0.1
    return min(score, 1.0)


def has_structure_evidence(row: dict[str, str]) -> bool:
    if numeric(row.get("structural_score", "")) == numeric(row.get("structural_score", "")):
        return numeric(row.get("structural_score", "")) > 0
    tm = numeric(row.get("tm_score_mean", ""))
    return tm == tm and tm > 0


def fedkea_is_enzyme(row: dict[str, str]) -> bool:
    value = (row.get("fedkea_is_enzyme", "") or "").strip().lower()
    return value in ("true", "1", "yes", "y")


def fedkea_target_match(row: dict[str, str], target_ecs: set[str]) -> bool:
    if not target_ecs:
        return False
    final_result = (row.get("fedkea_final_result", "") or "").strip()
    if not final_result:
        return False
    normalized = final_result.replace(" ", "").lstrip("EC:")
    return normalized in target_ecs


def annotation_matches_target(row: dict[str, str], target_ecs: set[str], target_names: set[str]) -> bool:
    source_ec = (row.get("source_ec_number", "") or "").strip()
    if target_ecs and source_ec:
        source_norm = source_ec.replace(" ", "").lstrip("EC:")
        if source_norm in target_ecs:
            return True
    if target_names:
        text_parts = [
            row.get("source_product", ""),
            row.get("source_description", ""),
            row.get("source_protein_name", ""),
            row.get("existing_annotation", ""),
            row.get("annotation", ""),
        ]
        haystack = " ".join(part.lower() for part in text_parts if part).strip()
        if haystack and any(name in haystack for name in target_names):
            return True
    return False


def is_usalign_structure(row: dict[str, str]) -> bool:
    support = (row.get("structure_support", "") or "").strip().lower()
    if support and support in ("1", "true", "yes", "usalign"):
        return True
    tool = (row.get("tool", "") or "").strip().lower()
    return bool(tool and "usal" in tool)


def is_deer_structure(row: dict[str, str]) -> bool:
    support = (row.get("structure_support", "") or "").strip().lower()
    return support in ("deer", "deer_results") or bool(row.get("deer_distance") or row.get("deer_rank"))


def priority_rule(
    row: dict[str, str],
    threshold: float,
    target_ecs: set[str],
    target_names: set[str] = frozenset(),
) -> tuple[int, str]:
    structural = structural_component(row)
    tm = numeric(row.get("tm_score_mean", ""))
    tm_threshold_met = tm == tm and tm >= threshold
    sequence = numeric(row.get("sequence_score", ""))

    if sequence > 0 and annotation_matches_target(row, target_ecs, target_names):
        return 1, "SEQUENCE_ANNOTATION_CONFIRMED"

    if structural > 0 and not is_deer_structure(row):
        # Structure evidence is used when the sequence+annotation fast path
        # did not already confirm the target function.
        if fedkea_is_enzyme(row):
            if fedkea_target_match(row, target_ecs):
                return 2, "USALIGN_TARGET_EC"
            return 4, "USALIGN_OTHER_EC"
        if (row.get("fedkea_is_enzyme", "") or "").strip():
            return 5, "USALIGN_NOT_ENZYME"
        return 6, "USALIGN_UNVALIDATED"

    if structural > 0 and is_deer_structure(row):
        if fedkea_is_enzyme(row):
            return 3, "DEER_FEDKEA_CONFIRMED"
        return 7, "DEER_FALLBACK"

    if sequence > 0:
        return 8, "SEQUENCE_ONLY"

    return 9, "ANNOTATION_ONLY"


def tier_outputs(
    row: dict[str, str],
    threshold: float,
    target_ecs: set[str],
    target_names: set[str],
) -> None:
    order, rule = priority_rule(row, threshold, target_ecs, target_names)
    row["priority_order"] = str(order)
    row["priority_rule"] = rule
    row["priority_tier"] = rule


def annotate_ranks(rows: list[dict[str, str]], field: str, score_field: str) -> None:
    ranked = [row for row in rows if numeric(row.get(score_field, "")) == numeric(row.get(score_field, ""))]
    ranked.sort(key=lambda row: numeric(row.get(score_field, "")), reverse=True)
    for rank, row in enumerate(ranked, start=1):
        row[field] = str(rank)


def annotate_ranks_by(rows: list[dict[str, str]], field: str, key) -> None:
    """Rank rows by an arbitrary non-negative key function, highest first."""
    ranked = [row for row in rows if key(row) > 0]
    ranked.sort(key=key, reverse=True)
    for rank, row in enumerate(ranked, start=1):
        row[field] = str(rank)


def score_rows(
    rows: list[dict[str, str]],
    threshold: float,
    target_ecs: set[str],
    target_names: set[str],
    policy: str,
    no_sort: bool,
    rank_by: str = "structure",
) -> list[dict[str, str]]:
    sequence_scores = [value for row in rows if (value := numeric(row.get("sequence_score", ""))) == value and value > 0]
    max_sequence_score = max(sequence_scores, default=0.0)

    # `rank_by="structure"` makes structural similarity (TM-score) the primary key:
    # rows carrying a TM-score are ordered by it descending, and rows without one
    # (fast-path rows that skipped structure, DEER rows with only a distance,
    # sequence-only, annotation-only) follow, ordered among themselves by
    # priority_order. `rank_by="priority"` keeps the earlier tier-first ordering.
    structure_first = rank_by == "structure"

    augmented: list[tuple[float, ...]] = []
    for row in rows:
        sequence = sequence_component(row, max_sequence_score)
        annotation = annotation_component(row)
        tier_outputs(row, threshold, target_ecs, target_names)
        priority_order = int(row["priority_order"])
        structural = structural_component(row)
        # overall_score is a display value; overall_rank is the deliverable field.
        # In structure-first mode the structural term dominates so score and rank
        # agree, and the priority term only breaks near-ties.
        if structure_first:
            score = (
                10000.0 * structural
                + 10.0 * (9 - priority_order)
                + 2.0 * sequence
                + 0.2 * annotation
            )
        else:
            score = 1000.0 - float(priority_order) * 100.0 + 20.0 * structural + 10.0 * sequence + 2.0 * annotation
        row["overall_score"] = f"{score:.4f}"
        row["rank_policy"] = policy
        candidate_id = row.get("candidate_id", row.get("protein_accession", ""))
        key = (
            (-structural, priority_order) if structure_first else (priority_order, -structural)
        ) + (-sequence, -annotation, str(candidate_id), f"{score:.10f}")
        augmented.append(key + (row,))

    annotate_ranks(rows, "sequence_rank", "sequence_score")
    # structural_rank must use the same TM component as the structure-first
    # ordering, otherwise a row carrying only tm_score_mean (no structural_score)
    # would be treated as having no structure by one and not the other.
    annotate_ranks_by(rows, "structural_rank", structural_component)

    if no_sort:
        ordered = rows
    else:
        ordered = [item[-1] for item in sorted(augmented, key=lambda item: item[:-1])]
    for rank, row in enumerate(ordered, start=1):
        row["overall_rank"] = str(rank)
    return ordered


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.input.is_file():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 2

    rows, fields = read_tsv(args.input)
    if not rows:
        for field in OUTPUT_FIELDS:
            if field not in fields:
                fields.append(field)
        write_tsv(args.output or args.input, fields, [])
        print(f"wrote {args.output or args.input} (0 rows: no candidates to score)")
        return 0

    for field in OUTPUT_FIELDS:
        if field not in fields:
            fields.append(field)

    target_ecs = {ec.strip() for ec in args.target_ec.split(",") if ec.strip()}
    target_names = {name.strip().lower() for name in args.target_name.split(",") if name.strip()}
    if not target_names:
        # The annotation half of the fast path can only be evaluated by name. Say so
        # rather than silently leaving SEQUENCE_ANNOTATION_CONFIRMED unreachable: a
        # quiet no-op here previously produced two different tiers for one dataset.
        carries_annotation = any(
            (row.get("source_product") or row.get("existing_annotation") or row.get("annotation"))
            for row in rows
        )
        if carries_annotation:
            print(
                "warning: --target-name not given, so the sequence+annotation fast path "
                "(SEQUENCE_ANNOTATION_CONFIRMED) cannot be evaluated even though some rows "
                "carry annotations. Pass --target-name with comma-separated enzyme "
                "names/synonyms to enable it.",
                file=sys.stderr,
            )
    policy = args.policy or (
        "structure_first_tm_score" if args.rank_by == "structure" else "priority_rule_first"
    )
    scored = score_rows(
        rows, args.tm_threshold, target_ecs, target_names, policy, args.no_sort, args.rank_by
    )
    output = args.output or args.input
    write_tsv(output, fields, scored)
    print(f"wrote {output} ({len(scored)} rows; policy={policy}; rank_by={args.rank_by})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
