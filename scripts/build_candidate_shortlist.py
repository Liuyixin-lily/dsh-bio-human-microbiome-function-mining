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

# every component that feeds the score must be exported, or a reader cannot reproduce it
ENZYME_FIELDS = [
    "rank", "target_id", "gene", "name", "uniprot", "ec", "site_process",
    "evidence_status", "evidence_refs", "evidence_note", "ranking_note",
    "known_score", "discovery_score", "priority_score", "selection_status",
    "scored_components",
    "site_evidence_score", "disease_relevance_score", "biochemical_clarity_score",
    "sequence_structure_score", "microbial_plausibility_score",
    "assay_feasibility_score", "novelty_score", "score_sources",
    "score_basis", "scoring_policy",
]
TAXA_FIELDS = [
    "rank", "taxon_id", "genus", "species", "display_name",
    "evidence_status", "evidence_refs", "ranking_note",
    "priority_score", "selection_status", "scored_components",
    "site_presence_score", "disease_site_relevance_score",
    "experimental_accessibility_score", "genome_availability_score",
    "metabolic_plausibility_score", "score_sources", "score_basis", "scoring_policy",
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


def normalize_name(value: str) -> str:
    """'azoreductase (Azo1, FMN-dependent NADPH)' and 'azoreductase' are the same candidate."""
    text = (value or "").strip().lower()
    text = text.split("(")[0]
    text = text.replace("/", " ")
    return " ".join(text.split())


def merge_registries(paths: list[Path], name_key: str | None = None) -> list[dict[str, str]]:
    """Union of registries, first occurrence wins per target_id; later files only fill gaps."""
    merged: dict[str, dict[str, str]] = {}
    by_name: dict[str, str] = {}
    order: list[str] = []
    for path in paths:
        for row in read_tsv(path):
            key = (row.get("target_id") or row.get("taxon_id") or "").strip()
            if not key:
                continue
            if name_key:
                # the same enzyme can arrive under two ids (a library id and a literature-derived
                # id); collapse on name+EC so the candidate list does not list it twice
                identity = f"{normalize_name(row.get(name_key) or '')}|{(row.get('ec') or '').strip()}"
                if identity in by_name:
                    existing = merged[by_name[identity]]
                    for field, value in row.items():
                        if value and not existing.get(field):
                            existing[field] = value
                    continue
                by_name[identity] = key
            if key not in merged:
                merged[key] = dict(row)
                order.append(key)
                continue
            for field, value in row.items():
                if value and not merged[key].get(field):
                    merged[key][field] = value
    return [merged[key] for key in order]


def collapse_by_name(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """One row per enzyme name when the only difference is an EC one source did not record.

    Two sources may know the same enzyme under different ids and one of them may omit the EC. That
    is not two candidates; it is the same candidate with partial knowledge.
    """
    groups: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        groups.setdefault(normalize_name(row.get("name") or ""), []).append(index)
    drop: set[int] = set()
    for indexes in groups.values():
        if len(indexes) < 2:
            continue
        with_ec = [i for i in indexes if (rows[i].get("ec") or "").strip()]
        if len(with_ec) != 1:
            continue
        keeper = rows[with_ec[0]]
        for index in indexes:
            if index == with_ec[0]:
                continue
            for field, value in rows[index].items():
                if value and not keeper.get(field):
                    keeper[field] = value
            drop.add(index)
    return [row for index, row in enumerate(rows) if index not in drop]


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
                fact = {
                    "evidence_status": str(enzyme.get("evidence_status") or ""),
                    "evidence_refs": ", ".join(enzyme.get("evidence_refs") or []),
                    "evidence_note": str(enzyme.get("provenance_note_zh") or ""),
                }
                enzymes[enzyme.get("id", "")] = fact
                # a literature-derived registry names the same enzyme differently; index by the
                # normalised name so a merge cannot silently drop the verified status
                for key_field in ("enzyme_name_en", "enzyme_name_zh"):
                    name = normalize_name(enzyme.get(key_field) or "")
                    if name:
                        enzymes.setdefault(f"name:{name}", fact)
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


def literature_refs(path: Path | None) -> dict[str, list[str]]:
    """candidate_id -> PMIDs from literature_evidence.tsv, for rows discovered from literature."""
    refs: dict[str, list[str]] = {}
    if path is None or not path.is_file():
        return refs
    for row in read_tsv(path):
        if (row.get("verified") or "").strip().lower() not in ("yes", "true", "1"):
            continue
        ref = (row.get("reference_id") or "").strip()
        key = (row.get("candidate_id") or row.get("protein_accession") or "").strip()
        if key and ref:
            refs.setdefault(key, []).append(ref)
    return refs


def annotate(rows: list[dict[str, str]], facts: dict[str, dict[str, str]], id_field: str,
             lit_refs: dict[str, list[str]] | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        key = (row.get(id_field) or "").strip()
        name = normalize_name(row.get("name") or "")
        fact = (
            facts.get(key)
            or facts.get(f"name:{name}")
            or facts.get(str(row.get("name") or "").lower())
            or {}
        )
        status = fact.get("evidence_status") or row.get("evidence_status") or ""
        refs = fact.get("evidence_refs") or ""
        if not status and lit_refs and key in lit_refs:
            # the enzyme name was found in retrieved abstracts: that is a literature-retrieved
            # candidate, not a verified functional claim
            status = "literature_retrieved（摘要提及）"
            refs = ", ".join(lit_refs[key])
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


COMPONENTS = ("site_evidence_score", "disease_relevance_score", "biochemical_clarity_score",
              "sequence_structure_score", "microbial_plausibility_score",
              "assay_feasibility_score", "novelty_score")
TAXA_COMPONENTS = ("site_presence_score", "disease_site_relevance_score",
                   "experimental_accessibility_score", "genome_availability_score",
                   "metabolic_plausibility_score")


def count_scored(row: dict[str, Any], components: tuple[str, ...]) -> int:
    return sum(1 for key in components if str(row.get(key) or "").strip() not in ("", "0.000"))


GENERIC_SOURCES = ("auto:taxa_list", "auto:registry")


def has_specific_evidence(row: dict[str, Any]) -> bool:
    """At least one scored component comes from something more specific than the species list.

    Every taxon in the list has abundance and an assembly count, so a bare `>= 2 components` rule
    recommended all 257 of them. What makes a taxon worth naming is a library focus, a retrieved
    citation, or a genome-search hit - not the fact that it appears in the list at all.
    """
    raw = str(row.get("score_sources") or "")
    for part in raw.split(";"):
        if "=" not in part:
            continue
        key, source = part.split("=", 1)
        source = source.strip()
        if source in ("manual", "missing") or source.startswith("not_applicable"):
            continue
        if not source.startswith(GENERIC_SOURCES):
            return True
    return False


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
    parser.add_argument("--rank-by", choices=("evidence", "score"), default="evidence",
                        help="evidence (default): evidence tier first, priority_score inside the tier, "
                             "so a hand-scored but unreferenced entry cannot outrank a referenced one; "
                             "score: pure priority_score order")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rank_by = getattr(args, "rank_by", "evidence")
    if not args.enzymes and not args.taxa:
        print("error: pass at least one --enzymes or --taxa registry", file=sys.stderr)
        return 2
    outdir = args.output_dir
    outdir.mkdir(parents=True, exist_ok=True)
    work = outdir / "_registries"
    work.mkdir(exist_ok=True)

    enzyme_registry = None
    if args.enzymes:
        merged = collapse_by_name(merge_registries(args.enzymes, name_key="name"))
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
    lit_refs = literature_refs(args.literature)
    enzyme_rows: list[dict[str, Any]] = []
    taxa_rows: list[dict[str, Any]] = []

    ranked_enzymes = outdir / "enzyme_priority_ranking.tsv"
    if ranked_enzymes.is_file():
        enzyme_rows = annotate(read_tsv(ranked_enzymes), facts_enzymes, "target_id", lit_refs)
        annotate_ranking_note(enzyme_rows, "its own registry")
        for row in enzyme_rows:
            row["scored_components"] = count_scored(row, COMPONENTS)
        if rank_by == "evidence":
            enzyme_rows.sort(key=lambda r: (evidence_rank(r), str(r.get("target_id"))))
        else:
            # recommended ranking: score first, and the evidence column stays visible next to it
            enzyme_rows.sort(key=lambda r: (-(float(r.get("priority_score") or 0)),
                                            -int(r.get("scored_components") or 0),
                                            str(r.get("target_id"))))
        for i, row in enumerate(enzyme_rows, 1):
            row["rank"] = i
        write_tsv(outdir / "candidate_enzymes.tsv", enzyme_rows, ENZYME_FIELDS)
        # a recommendation needs more than one scored component; below that the "rank" is only a
        # restatement of the single component that happened to be filled
        recommended_rows = [r for r in enzyme_rows if int(r.get("scored_components") or 0) >= 2]
        for i, row in enumerate(recommended_rows, 1):
            row["rank"] = i
        write_tsv(outdir / "recommended_enzymes.tsv", recommended_rows, ENZYME_FIELDS)
    ranked_taxa = outdir / "taxa_priority_ranking.tsv"
    if ranked_taxa.is_file():
        taxa_rows = annotate(read_tsv(ranked_taxa), {
            key.lower(): value for key, value in facts_taxa.items()
        }, "taxon_id")
        for row in taxa_rows:
            row["scored_components"] = count_scored(row, TAXA_COMPONENTS)
            binomial = f"{row.get('genus','')} {row.get('species','')}".strip().lower()
            fact = facts_taxa.get(binomial)
            if fact:
                row["evidence_status"] = "library_focus_taxon"
                row["evidence_refs"] = fact["evidence_refs"]
        taxa_rows.sort(key=lambda r: (-(float(r.get("priority_score") or 0)),
                                      -int(r.get("scored_components") or 0),
                                      str(r.get("taxon_id"))))
        for i, row in enumerate(taxa_rows, 1):
            row["rank"] = i
        write_tsv(outdir / "candidate_taxa.tsv", taxa_rows, TAXA_FIELDS)
        recommended_taxa = [
            r for r in taxa_rows
            if int(r.get("scored_components") or 0) >= 2 and has_specific_evidence(r)
        ]
        for i, row in enumerate(recommended_taxa, 1):
            row["rank"] = i
        write_tsv(outdir / "recommended_taxa.tsv", recommended_taxa, TAXA_FIELDS)

    (outdir / "candidate_shortlist.md").write_text(
        markdown(enzyme_rows, taxa_rows, args.library, args.enzymes, args.taxa), encoding="utf-8"
    )
    rec_e = len(recommended(enzyme_rows))
    rec_t = len(recommended(taxa_rows))
    rec_enzymes = [r for r in enzyme_rows if int(r.get("scored_components") or 0) >= 2]
    rec_taxa = [r for r in taxa_rows if int(r.get("scored_components") or 0) >= 2]
    print(f"candidate_enzymes.tsv   : {len(enzyme_rows)} row(s), {rec_e} literature_verified")
    print(f"recommended_enzymes.tsv : {len(rec_enzymes)} row(s) with >=2 scored components")
    print(f"candidate_taxa.tsv      : {len(taxa_rows)} row(s), {rec_t} literature_verified")
    print(f"recommended_taxa.tsv    : {len(rec_taxa)} row(s) with >=2 scored components")
    print(f"candidate_shortlist.md: {outdir / 'candidate_shortlist.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
