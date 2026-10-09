#!/usr/bin/env python3
"""Extract protein/CDS sequences for selected structural candidates.

Given a structural candidates TSV and a project config mapping candidate IDs to
source .faa / .ffn files, write:
  candidate_proteins.faa
  candidate_cds.ffn
  candidate_gene_evidence.tsv
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import sys


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", required=True, help="Path to structural candidates TSV.")
    parser.add_argument("--project", required=True, help="Path to project JSON.")
    parser.add_argument("--outdir", required=True, help="Output directory.")
    return parser.parse_args(argv)


def fasta_entries(path: pathlib.Path):
    header = None
    seq_parts = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if line.startswith(">"):
                if header is not None:
                    yield header, "".join(seq_parts)
                header = line
                seq_parts = []
            elif header is not None:
                seq_parts.append(line.strip())
    if header is not None:
        yield header, "".join(seq_parts)


def extract_by_id(fasta: pathlib.Path, wanted: set[str]) -> dict[str, tuple[str, str]]:
    found = {}
    for header, seq in fasta_entries(fasta):
        for cid in wanted:
            # Accept >WP_0001.1..., >lcl|NZ_..._cds_WP_0001.1_123 [protein_id=WP_0001.1]...,
            # or a bare header that starts with the candidate id.
            if (
                header == ">" + cid
                or header.startswith(">" + cid + " ")
                or (" " + cid + " ") in header
                or ("_" + cid + "_") in header
                or re.search(rf"\[protein_id={re.escape(cid)}\b", header)
            ):
                found[cid] = (header, seq)
                break
    return found


def read_project(project_path: pathlib.Path) -> dict:
    with project_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_candidate_ids(candidates_path: pathlib.Path) -> list[str]:
    ids = []
    with candidates_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            cid_key = "candidate_id"
            if cid_key not in row:
                for candidate in ("query_id", "protein_id", "id"):
                    if candidate in row and row[candidate]:
                        cid_key = candidate
                        break
            if row.get(cid_key):
                ids.append(row[cid_key])
    return ids


def find_source_map(project: dict) -> dict[str, dict]:
    """Return candidate_id -> {"protein_fasta": ..., "cds_fasta": ..., "source_genome": ...}.

    Looks for a dataset/demodata block that records candidate source FASTA paths.
    """
    source_map = {}
    genomes = ((project.get("candidate_sequences") or {}).get("genomes") or {})

    def collect_from(obj):
        if isinstance(obj, dict):
            if isinstance(obj.get("candidates"), dict):
                for cid, info in obj["candidates"].items():
                    if isinstance(info, dict):
                        source_map[cid] = {
                            "source_genome": info.get("source_genome", ""),
                            "protein_fasta": info.get("protein_fasta", ""),
                            "cds_fasta": info.get("cds_fasta", ""),
                        }
            for value in obj.values():
                collect_from(value)
        elif isinstance(obj, list):
            for item in obj:
                collect_from(item)

    collect_from(project)

    # For structural candidates (DEER hits in particular) the project JSON may
    # only declare genome-level source files. Fill missing candidate mappings
    # from each genome block when the candidate id is a WP accession that is
    # present in that genome's protein FASTA.
    for genome_name, genome_info in genomes.items():
        if not isinstance(genome_info, dict):
            continue
        protein_fasta = genome_info.get("protein_fasta", "")
        cds_fasta = genome_info.get("cds_fasta", "")
        if not protein_fasta or not cds_fasta:
            continue
        for cid, info in list(source_map.items()):
            if info.get("source_genome") == genome_name and info.get("protein_fasta"):
                continue
            if cid.startswith("WP_") and not info.get("protein_fasta"):
                candidates = extract_by_id(pathlib.Path(protein_fasta), {cid})
                if cid in candidates:
                    source_map[cid] = {
                        "source_genome": genome_name,
                        "protein_fasta": protein_fasta,
                        "cds_fasta": cds_fasta,
                    }
                    continue
    return source_map


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    candidates_path = pathlib.Path(args.candidates)
    project_path = pathlib.Path(args.project)
    outdir = pathlib.Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    candidate_ids = read_candidate_ids(candidates_path)
    project = read_project(project_path)
    source_map = find_source_map(project)

    rows = []
    protein_all = {}
    cds_all = {}
    for cid in candidate_ids:
        info = source_map.get(cid)
        if not info or not info.get("protein_fasta") or not info.get("cds_fasta"):
            print(f"MISSING source mapping for {cid}", file=sys.stderr)
            continue
        protein_fasta = pathlib.Path(info["protein_fasta"])
        cds_fasta = pathlib.Path(info["cds_fasta"])
        proteins = extract_by_id(protein_fasta, {cid})
        cdses = extract_by_id(cds_fasta, {cid})
        if cid not in proteins or cid not in cdses:
            print(f"MISSING {cid} protein={cid in proteins} cds={cid in cdses}", file=sys.stderr)
            continue

        prot_header, prot_seq = proteins[cid]
        cds_header, cds_seq = cdses[cid]
        protein_all[cid] = (prot_header, prot_seq)
        cds_all[cid] = (cds_header, cds_seq)

        def field(pattern: str, default: str = "") -> str:
            m = re.search(pattern, cds_header)
            return m.group(1) if m else default

        rows.append(
            {
                "candidate_id": cid,
                "source_genome": info.get("source_genome", ""),
                "locus_tag": field(r"\[locus_tag=([^\]]+)\]"),
                "protein": field(r"\[protein=([^\]]+)\]"),
                "protein_id": field(r"\[protein_id=([^\]]+)\]", cid),
                "location": field(r"\[location=([^\]]+)\]"),
                "protein_fai_header": prot_header[1:],
                "cds_fai_header": cds_header[1:],
                "protein_length": len(prot_seq),
                "cds_length": len(cds_seq),
            }
        )

    if not rows:
        print("No candidate sequences extracted.", file=sys.stderr)
        return 1

    with (outdir / "candidate_proteins.faa").open("w", encoding="utf-8", newline="\n") as f:
        for cid in [r["candidate_id"] for r in rows]:
            header, seq = protein_all[cid]
            f.write(header + "\n")
            for i in range(0, len(seq), 60):
                f.write(seq[i : i + 60] + "\n")

    with (outdir / "candidate_cds.ffn").open("w", encoding="utf-8", newline="\n") as f:
        for cid in [r["candidate_id"] for r in rows]:
            header, seq = cds_all[cid]
            f.write(header + "\n")
            for i in range(0, len(seq), 60):
                f.write(seq[i : i + 60] + "\n")

    with (outdir / "candidate_gene_evidence.tsv").open("w", encoding="utf-8", newline="\n") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print("wrote", outdir)
    for row in rows:
        print("\t".join([row["candidate_id"], row["source_genome"], row["locus_tag"], row["location"], row["protein"]]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
