#!/usr/bin/env python3
"""Produce the candidate enzyme / candidate taxa lists a user actually chooses from.

This is the output layer of entry B. It deliberately keeps two sections instead of one ranked
list, because collapsing them is what makes a shortlist look authoritative when it is not:

  1. `recommended` — entries with `evidence_status=literature_verified` and real references.
     These are what "work on this first" can mean without overclaiming.
  2. `candidate_pool` — everything else that was supplied or curated: user-provided rankings,
     starter-domain entries, host-enzyme templates. They are useful as search space and as a
     menu, but they have no verified reference behind them, and each row says so.

Inputs are whatever the user has:

    --enzymes  one or more enzyme registries (the plugin's own TSV, or a legacy
               select-candidate `enzyme_ranking.tsv` with `skin_*` columns)
    --taxa     one or more taxa registries (e.g. from import_taxon_list.py)
    --library  a library domain, which supplies evidence status and references per enzyme
    --genomes / --literature  optional artifacts that make more score components derivable

Outputs, under --output-dir:

    candidate_enzymes.tsv      one row per candidate enzyme, with evidence columns
    candidate_taxa.tsv         one row per candidate taxon
    candidate_shortlist.md     counts per evidence tier and what is still missing
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SCORE_SCRIPT = SCRIPT_DIR / "score_target_priorities.py"

ENZYME_FIELDS = [
    "rank", "target_id", "gene", "name", "uniprot", "ec",
    "evidence_status", "evidence_refs", "evidence_note", "ranking_note",
    "priority_score", "site_evidence_score", "biochemical_clarity_score",
    "assay_feasibility_score", "selection_status", "score_sources",
]
TAXA_FIELDS = [
    "rank", "taxon_id", "genus", "species", "display_name",
    "evidence_status", "evidence_refs", "ranking_note",
    "priority_score", "site_presence_score", "metabolic_plausibility_score",
    "metabolic_plausibility_score_source", "selection_status", "score_sources",
]


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def merge_registries(paths: list[Path]) -> list[dict[str, str]]:
    """Union of registries, first occurrence wins per target_id; later files only fill gaps."""
    merged: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for path in paths:
        for row in read_tsv(path):
            key = (row.get("target_id") or row.get("taxon_id") or "").strip()
            if not key:
                continue
            if key not in merged:
                merged[key] = dict(row)
                order.append(key)
                continue
            for field, value in row.items():
                if value and not merged[key].get(field):
                    merged[key][field] = value
    return [merged[key] for key in order]


def library_facts(library_paths: list[Path]) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    enzymes: dict[str, dict[str, str]] = {}
    taxa: dict[str, dict[str, str]] = {}
    for path in library_paths:
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        domain = payload.get("domain") or {}
        for process in domain.get("processes") or []:
            for enzyme in process.get("enzymes") or []:
                enzymes[enzyme.get("id", "")] = {
                    "evidence_status": str(enzyme.get("evidence_status") or ""),
                    "evidence_refs": ", ".join(enzyme.get("evidence_refs") or []),
                    "evidence_note": str(enzyme.get("provenance_note_zh") or ""),
                }
        for taxon in domain.get("focus_taxa") or []:
            name = str(taxon.get("taxon") or "").strip()
            if name:
                taxa[name.lower()] = {
                    "evidence_status": str(taxon.get("attention") or ""),
                    "evidence_refs": str(taxon.get("role_zh") or ""),
                }
    return enzymes, taxa


def score(
    enzymes: Path | None,
    taxa: Path | None,
    library: list[Path],
    genomes: Path | None,
    literature: Path | None,
    site: str | None,
    outdir: Path,
) -> None:
    cmd = [sys.executable, str(SCORE_SCRIPT)]
    if enzymes is not None:
        cmd += ["--enzymes", str(enzymes)]
    if taxa is not None:
        cmd += ["--taxa", str(taxa)]
    for path in library:
        cmd += ["--library", str(path)]
    if genomes is not None:
        cmd += ["--genomes", str(genomes)]
    if literature is not None:
        cmd += ["--literature", str(literature)]
    if site:
        cmd += ["--site", site]
    cmd += ["--auto-score", "--allow-missing-scores", "--output", str(outdir)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr[-1500:], file=sys.stderr)
        raise SystemExit("scoring failed")


def annotate(rows: list[dict[str, str]], facts: dict[str, dict[str, str]], id_field: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        key = (row.get(id_field) or "").strip()
        fact = facts.get(key) or facts.get(str(row.get("name") or "").lower()) or {}
        status = fact.get("evidence_status") or row.get("evidence_status") or ""
        refs = fact.get("evidence_refs") or ""
        if not status:
            # a registry the user supplied (e.g. an old select-candidate ranking) carries scores but
            # no references; that is "user_supplied", not "unknown"
            status = "user_supplied（无 references）"
        out.append({
            **row,
            "evidence_status": status or "unknown",
            "evidence_refs": refs,
            "evidence_note": fact.get("evidence_note", ""),
        })
    return out


def recommended(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if str(r.get("evidence_status", "")).startswith("literature_verified") and r.get("evidence_refs")]


def evidence_rank(row: dict[str, Any]) -> tuple[int, float]:
    """Order by evidence strength first, score second.

    Scores are not comparable across sources: a hand-scored legacy registry has every component
    filled, while a starter-domain entry only has what can be derived. Sorting on the score alone
    puts a fully hand-scored unknown first and the single verified entry last.
    """
    status = str(row.get("evidence_status", ""))
    if status.startswith("literature_verified") and row.get("evidence_refs"):
        tier = 0
    elif row.get("evidence_refs"):
        tier = 1          # references retrieved, not sufficient for the claim
    elif status.startswith("library_focus_taxon"):
        tier = 1
    else:
        tier = 2          # user-supplied or curated prior, no references
    return tier, -(float(row.get("priority_score") or 0))


def annotate_ranking_note(rows: list[dict[str, Any]], source_label: str) -> None:
    for row in rows:
        tier = evidence_rank(row)[0]
        if tier == 0:
            row["ranking_note"] = "literature_verified; ranked above the pool regardless of score"
        elif tier == 1:
            row["ranking_note"] = "references retrieved but not sufficient for the claim"
        else:
            row["ranking_note"] = (
                f"score from {source_label}; not comparable with verified entries or with a "
                "differently-scored source"
            )


def markdown(
    enzyme_rows: list[dict[str, Any]],
    taxa_rows: list[dict[str, Any]],
    library_paths: list[Path],
    enzyme_inputs: list[Path],
    taxa_inputs: list[Path],
) -> str:
    rec_e = recommended(enzyme_rows)
    rec_t = recommended(taxa_rows)
    lines = [
        "# Candidate enzyme / candidate taxa shortlist",
        "",
        "Two sections on purpose: a shortlist that mixes verified and unverified entries hides",
        "which is which, and that is the one thing a reader needs to know before choosing.",
        "",
        "## Inputs",
        "",
    ]
    for label, paths in (("enzymes", enzyme_inputs), ("taxa", taxa_inputs), ("library", library_paths)):
        for path in paths:
            lines.append(f"- {label}: `{path}`")
    lines += [
        "",
        "## 1. Recommended (literature_verified with references)",
        "",
    ]
    if rec_e:
        lines += ["| enzyme | EC | refs |", "| --- | --- | --- |"]
        lines += [f"| {r.get('name') or r.get('target_id')} | {r.get('ec','')} | {r['evidence_refs']} |" for r in rec_e]
    else:
        lines.append("- no enzyme reaches `literature_verified`; see the pool below and attach evidence first.")
    lines.append("")
    if rec_t:
        lines += ["| taxon | basis |", "| --- | --- |"]
        lines += [f"| {r.get('display_name') or r.get('taxon_id')} | {r['evidence_refs'][:80]} |" for r in rec_t]
    else:
        lines.append("- no taxon carries `literature_verified` evidence.")
    lines += [
        "",
        "## 2. Candidate pool (usable as search space, not as a conclusion)",
        "",
        f"- enzymes: {len(enzyme_rows)} (recommended {len(rec_e)})",
        f"- taxa: {len(taxa_rows)} (recommended {len(rec_t)})",
        "",
        "Every pool row carries `evidence_status` and `evidence_refs`. A user-provided ranking has",
        "no references until someone attaches them; a starter-domain entry is a curation prior.",
        "",
        "## What is still missing",
        "",
        "- `--genomes` (genome-search output) makes `genome_availability_score` and `site_presence_score`",
        "  derivable for taxa.",
        "- `--literature` (literature_evidence.tsv, verified rows only) makes `site_evidence_score`",
        "  and `disease_relevance_score` derivable for enzymes.",
        "- anything still empty is counted as 0 in the weighted sum and marked `missing` in",
        "  `score_sources`, so the ranking never pretends the gap is evidence.",
        "",
    ]
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Produce candidate enzyme and candidate taxa shortlists with evidence columns.",
    )
    parser.add_argument("--enzymes", type=Path, action="append", default=[], help="Enzyme registry TSV; repeatable.")
    parser.add_argument("--taxa", type=Path, action="append", default=[], help="Taxa registry TSV; repeatable.")
    parser.add_argument("--library", type=Path, action="append", default=[], help="Library domain JSON; repeatable.")
    parser.add_argument("--genomes", type=Path, default=None, help="genome-search TSV.")
    parser.add_argument("--literature", type=Path, default=None, help="literature_evidence.tsv.")
    parser.add_argument("--site", default=None, help="Body site id (skin / gut / oral ...).")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.enzymes and not args.taxa:
        print("error: pass at least one --enzymes or --taxa registry", file=sys.stderr)
        return 2
    outdir = args.output_dir
    outdir.mkdir(parents=True, exist_ok=True)
    work = outdir / "_registries"
    work.mkdir(exist_ok=True)

    enzyme_registry = None
    if args.enzymes:
        merged = merge_registries(args.enzymes)
        enzyme_registry = work / "enzymes.merged.tsv"
        fields = list(merged[0])
        write_tsv(enzyme_registry, merged, fields)
        print(f"enzymes: merged {sum(len(read_tsv(p)) for p in args.enzymes)} row(s) -> {len(merged)} unique")
    taxa_registry = None
    if args.taxa:
        merged = merge_registries(args.taxa)
        taxa_registry = work / "taxa.merged.tsv"
        fields = list(merged[0])
        write_tsv(taxa_registry, merged, fields)
        print(f"taxa   : merged {sum(len(read_tsv(p)) for p in args.taxa)} row(s) -> {len(merged)} unique")

    score(enzyme_registry, taxa_registry, args.library, args.genomes, args.literature, args.site, outdir)

    facts_enzymes, facts_taxa = library_facts(args.library)
    enzyme_rows: list[dict[str, Any]] = []
    taxa_rows: list[dict[str, Any]] = []

    ranked_enzymes = outdir / "enzyme_priority_ranking.tsv"
    if ranked_enzymes.is_file():
        enzyme_rows = annotate(read_tsv(ranked_enzymes), facts_enzymes, "target_id")
        annotate_ranking_note(enzyme_rows, "its own registry")
        enzyme_rows.sort(key=lambda r: (evidence_rank(r), str(r.get("target_id"))))
        for i, row in enumerate(enzyme_rows, 1):
            row["rank"] = i
        write_tsv(outdir / "candidate_enzymes.tsv", enzyme_rows, ENZYME_FIELDS)
    ranked_taxa = outdir / "taxa_priority_ranking.tsv"
    if ranked_taxa.is_file():
        taxa_rows = annotate(read_tsv(ranked_taxa), {
            key.lower(): value for key, value in facts_taxa.items()
        }, "taxon_id")
        for row in taxa_rows:
            binomial = f"{row.get('genus','')} {row.get('species','')}".strip().lower()
            fact = facts_taxa.get(binomial)
            if fact:
                row["evidence_status"] = "library_focus_taxon"
                row["evidence_refs"] = fact["evidence_refs"]
        write_tsv(outdir / "candidate_taxa.tsv", taxa_rows, TAXA_FIELDS)

    (outdir / "candidate_shortlist.md").write_text(
        markdown(enzyme_rows, taxa_rows, args.library, args.enzymes, args.taxa), encoding="utf-8"
    )
    rec_e = len(recommended(enzyme_rows))
    rec_t = len(recommended(taxa_rows))
    print(f"candidate_enzymes.tsv : {len(enzyme_rows)} row(s), {rec_e} literature_verified")
    print(f"candidate_taxa.tsv    : {len(taxa_rows)} row(s), {rec_t} literature_verified")
    print(f"candidate_shortlist.md: {outdir / 'candidate_shortlist.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
