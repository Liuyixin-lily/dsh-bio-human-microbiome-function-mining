#!/usr/bin/env python3
"""Build a Target Function Card JSON from user-supplied fields.

The output follows human_microbiome_function_mining/schemas/target_function_card.schema.json.
Unknown literal fields are written as empty strings; missing file fields are
written as empty paths so the schema remains valid and the gap is visible.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SCHEMA_REQUIRED = [
    "target_id",
    "enzyme_name",
    "ec",
    "reaction",
    "substrate",
    "product",
    "cofactor",
    "structural_fold",
    "pathway",
    "catalytic_residues_file",
    "structure_file",
    "sequence_file",
    "known_enzymes",
    "known_microbial_enzymes",
    "input_source",
    "notes",
]


def default_card() -> dict[str, Any]:
    return {
        "target_id": "",
        "enzyme_name": "",
        "ec": "",
        "reaction": "",
        "substrate": "",
        "product": "",
        "cofactor": "",
        "structural_fold": "",
        "pathway": "",
        "catalytic_residues_file": "",
        "structure_file": "",
        "sequence_file": "",
        "known_enzymes": [],
        "known_microbial_enzymes": [],
        "input_source": "manual",
        "notes": "",
    }


def str_to_opt(value: str | None) -> str:
    return "" if value is None else value.strip()


def comma_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def build_card(
    *,
    target_id: str | None = None,
    enzyme_name: str | None = None,
    ec: str | None = None,
    reaction: str | None = None,
    substrate: str | None = None,
    product: str | None = None,
    cofactor: str | None = None,
    structural_fold: str | None = None,
    pathway: str | None = None,
    catalytic_residues_file: str | None = None,
    structure_file: str | None = None,
    sequence_file: str | None = None,
    known_enzymes: str | None = None,
    known_microbial_enzymes: str | None = None,
    input_source: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    card = default_card()
    card["target_id"] = str_to_opt(target_id)
    card["enzyme_name"] = str_to_opt(enzyme_name)
    card["ec"] = str_to_opt(ec)
    card["reaction"] = str_to_opt(reaction)
    card["substrate"] = str_to_opt(substrate)
    card["product"] = str_to_opt(product)
    card["cofactor"] = str_to_opt(cofactor)
    card["structural_fold"] = str_to_opt(structural_fold)
    card["pathway"] = str_to_opt(pathway)
    card["catalytic_residues_file"] = str_to_opt(catalytic_residues_file)
    card["structure_file"] = str_to_opt(structure_file)
    card["sequence_file"] = str_to_opt(sequence_file)
    card["known_enzymes"] = comma_list(known_enzymes)
    card["known_microbial_enzymes"] = comma_list(known_microbial_enzymes)
    card["input_source"] = str_to_opt(input_source) or "manual"
    card["notes"] = str_to_opt(notes)
    return card


def load_project_fields(project_path: Path) -> tuple[dict[str, Any], Path]:
    if project_path.is_dir():
        project_path = project_path / "project.json"
    if not project_path.is_file():
        print(f"project file not found: {project_path}", file=sys.stderr)
        raise SystemExit(2)
    try:
        data = json.loads(project_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"failed to read project JSON: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    target_cfg = data.get("target_function_card") or {}
    input_cfg = data.get("inputs") or {}
    return {
        "target_id": target_cfg.get("target_id"),
        "enzyme_name": target_cfg.get("enzyme_name"),
        "ec": target_cfg.get("ec"),
        "reaction": target_cfg.get("reaction"),
        "substrate": target_cfg.get("substrate"),
        "product": target_cfg.get("product"),
        "cofactor": target_cfg.get("cofactor"),
        "structural_fold": target_cfg.get("structural_fold"),
        "pathway": target_cfg.get("pathway"),
        "catalytic_residues_file": input_cfg.get("target_catalytic_residues_file"),
        "structure_file": input_cfg.get("target_structure_pdb"),
        "sequence_file": input_cfg.get("target_sequence_fasta"),
        "known_enzymes": target_cfg.get("known_enzymes"),
        "known_microbial_enzymes": target_cfg.get("known_microbial_enzymes"),
        "input_source": target_cfg.get("input_source"),
        "notes": target_cfg.get("notes"),
    }, project_path.parent


def validate_card(card: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in SCHEMA_REQUIRED:
        if key not in card:
            errors.append(f"missing required field: {key}")
        continue
    if card.get("input_source", "manual") not in {
        "sequence",
        "ec",
        "reaction",
        "manual",
    }:
        errors.append("input_source must be one of: sequence, ec, reaction, manual")
    return errors


def write_json(card: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(card, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a machine-readable target function card."
    )
    parser.add_argument("--output", type=Path, required=True, help="Output target_function_card.json")
    parser.add_argument(
        "--project",
        type=Path,
        help="Optional project.json. Uses target_function_card and inputs fields; CLI flags override project values.",
    )
    parser.add_argument("--target-id", default=None, help="Stable target identifier.")
    parser.add_argument("--enzyme-name", default=None, help="Target enzyme name.")
    parser.add_argument("--ec", default=None, help="Full or family-level EC number.")
    parser.add_argument("--reaction", default=None, help="Reaction string.")
    parser.add_argument("--substrate", default=None, help="Substrate name.")
    parser.add_argument("--product", default=None, help="Product name.")
    parser.add_argument("--cofactor", default=None, help="Cofactor, or empty when unknown.")
    parser.add_argument("--structural-fold", default=None, help="Known structural fold, or empty.")
    parser.add_argument("--pathway", default=None, help="Related metabolic pathway.")
    parser.add_argument("--catalytic-residues-file", default=None, help="Project-relative catalytic residue TSV.")
    parser.add_argument("--structure-file", default=None, help="Project-relative target PDB/CIF.")
    parser.add_argument("--sequence-file", default=None, help="Project-relative target FASTA.")
    parser.add_argument("--known-enzymes", default=None, help="Comma-separated known enzyme identifiers.")
    parser.add_argument("--known-microbial-enzymes", default=None, help="Comma-separated microbial enzyme identifiers.")
    parser.add_argument(
        "--input-source",
        default="manual",
        choices=["sequence", "ec", "reaction", "manual"],
        help="How the target was originally supplied.",
    )
    parser.add_argument("--notes", default=None, help="Free-text notes.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.project is not None:
        project_fields, _project_root = load_project_fields(args.project)
    else:
        project_fields, _project_root = {}, Path.cwd()
    card = build_card(
        target_id=args.target_id or project_fields.get("target_id"),
        enzyme_name=args.enzyme_name or project_fields.get("enzyme_name"),
        ec=args.ec or project_fields.get("ec"),
        reaction=args.reaction or project_fields.get("reaction"),
        substrate=args.substrate or project_fields.get("substrate"),
        product=args.product or project_fields.get("product"),
        cofactor=args.cofactor or project_fields.get("cofactor"),
        structural_fold=args.structural_fold or project_fields.get("structural_fold"),
        pathway=args.pathway or project_fields.get("pathway"),
        catalytic_residues_file=args.catalytic_residues_file or project_fields.get("catalytic_residues_file"),
        structure_file=args.structure_file or project_fields.get("structure_file"),
        sequence_file=args.sequence_file or project_fields.get("sequence_file"),
        known_enzymes=args.known_enzymes or (",".join(project_fields["known_enzymes"]) if project_fields.get("known_enzymes") else None),
        known_microbial_enzymes=args.known_microbial_enzymes or (",".join(project_fields["known_microbial_enzymes"]) if project_fields.get("known_microbial_enzymes") else None),
        input_source=args.input_source if args.input_source != "manual" else (project_fields.get("input_source") or "manual"),
        notes=args.notes or project_fields.get("notes"),
    )
    errors = validate_card(card)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 2
    write_json(card, args.output)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
