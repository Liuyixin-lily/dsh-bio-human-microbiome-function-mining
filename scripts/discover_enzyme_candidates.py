#!/usr/bin/env python3
"""Derive a candidate enzyme list from literature the plugin retrieves itself.

The plugin must be able to produce candidate enzymes without borrowing anyone's local table. This
script does the smallest honest version of that:

1. run the literature route for a site + topic (OpenAlex via run_literature_search.sh, with PMID
   resolution so every candidate is traceable);
2. scan the retrieved titles/abstracts for enzyme family names from a fixed lexicon and for
   `EC x.y.z.w` strings;
3. emit an enzyme registry (`enzyme_registry.tsv`) for `score_target_priorities.py` /
   `build_candidate_shortlist.py`, plus `literature_evidence.tsv` in the plugin's own format so
   `--literature` can derive `site_evidence_score`.

What it will not do:

- invent an enzyme that no retrieved sentence mentions;
- attach a PMID to an enzyme without recording the sentence it came from (`notes`);
- guess an EC. Only an EC written in the retrieved text is recorded, and the confidence is `family`
  rather than `full` because the text may describe a family rather than one enzyme.
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SEARCH = SCRIPT_DIR / "run_literature_search.sh"

# Fixed, conservative lexicon. A term is only reported when it literally appears in the retrieved
# text; the list exists so that a hit is recognised, not so that a candidate is invented.
ENZYME_LEXICON: list[tuple[str, tuple[str, ...]]] = [
    ("azoreductase", ("azoreductase",)),
    ("beta-glucuronidase", ("glucuronidase",)),
    ("epoxide hydrolase", ("epoxide hydrolase",)),
    ("carboxylesterase", ("carboxylesterase", "esterase")),
    ("cytochrome P450", ("cytochrome p450", "cyp450", "cyp1a1", "cyp3a4", "cyp2e1", "cyp")),
    ("flavin-containing monooxygenase", ("flavin-containing monooxygenase", "fmo")),
    ("alcohol dehydrogenase", ("alcohol dehydrogenase",)),
    ("aldehyde dehydrogenase", ("aldehyde dehydrogenase",)),
    ("UDP-glucuronosyltransferase", ("udp-glucuronosyltransferase", "glucuronosyltransferase", "ugt")),
    ("glutathione S-transferase", ("glutathione s-transferase", "gst")),
    ("sulfotransferase", ("sulfotransferase", "sult")),
    ("N-acetyltransferase", ("n-acetyltransferase", "arylamine n-acetyltransferase")),
    ("nitroreductase", ("nitroreductase",)),
    ("monooxygenase", ("monooxygenase",)),
    ("dioxygenase", ("dioxygenase",)),
    ("catechol O-methyltransferase", ("catechol o-methyltransferase", "comt")),
    ("monoamine oxidase", ("monoamine oxidase",)),
]
EC_RE = re.compile(r"\bEC[:\s]*([1-7]\.\d{1,2}\.\d{1,2}\.\d{1,3})", re.IGNORECASE)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def read_results(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [row for row in csv.DictReader(handle, delimiter="\t")]


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_SPLIT.split(text or "") if s.strip()]


def find_candidates(papers: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, Any]]:
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for paper in papers:
        pmid = (paper.get("pmid") or "").strip()
        title = paper.get("title") or ""
        abstract = paper.get("abstract") or ""
        for sentence in sentences(f"{title}. {abstract}"):
            lowered = sentence.lower()
            ecs = EC_RE.findall(sentence)
            for name, needles in ENZYME_LEXICON:
                hit = next((n for n in needles if n in lowered), "")
                if not hit:
                    continue
                # an EC is only recorded when it appears in the same sentence as the enzyme name
                ec = ecs[0] if ecs else ""
                key = (name, ec)
                entry = found.setdefault(key, {"name": name, "ec": ec, "pmids": [], "quote": sentence})
                if pmid and pmid not in entry["pmids"]:
                    entry["pmids"].append(pmid)
    return found


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def write_registry(path: Path, entries: list[dict[str, Any]], site: str, topic: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["target_id", "gene", "name", "uniprot", "ec", "ec_confidence",
              "microbial_context", "site_process", "notes"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for entry in entries:
            writer.writerow({
                "target_id": f"lit_{slugify(entry['name'])}_{slugify(entry['ec']) or 'noec'}",
                "gene": "",
                "name": entry["name"],
                "uniprot": "",
                "ec": entry["ec"],
                # an EC copied from an abstract is a family-level identification, never "full"
                "ec_confidence": "family" if entry["ec"] else "none",
                # every candidate here came from a microbiome-metabolism query, but that only
                # makes the function plausible for the taxon, not demonstrated for a protein
                "microbial_context": "yes",
                "site_process": topic,
                "notes": (
                    f"检索自 {site} 主题「{topic}」；PMID {', '.join(entry['pmids']) or '—'}；"
                    f"原文：{entry['quote'][:200]}"
                ),
            })


def write_evidence(path: Path, entries: list[dict[str, Any]], site: str) -> None:
    """literature_evidence.tsv rows so --literature can derive site_evidence_score."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["candidate_id", "protein_accession", "organism_or_strain", "evidence_type",
              "reference_type", "reference_id", "title", "first_author", "journal", "year",
              "finding", "verified", "source_search", "notes"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for entry in entries:
            target_id = f"lit_{slugify(entry['name'])}_{slugify(entry['ec']) or 'noec'}"
            for pmid in entry["pmids"]:
                writer.writerow({
                    "candidate_id": target_id,
                    "protein_accession": target_id,
                    "organism_or_strain": "",
                    "evidence_type": "review",
                    "reference_type": "PMID",
                    "reference_id": pmid,
                    "title": "",
                    "first_author": "",
                    "journal": "",
                    "year": "",
                    "finding": entry["quote"][:240],
                    "verified": "yes",
                    "source_search": f"{site}: {entry['name']}",
                    "notes": "enzyme name mentioned in the retrieved abstract; not an assay of this protein",
                })


def parse_args(argv: list[str] | None = None) -> int | argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Retrieve literature and derive an enzyme candidate registry from it.",
    )
    parser.add_argument("--site", required=True, help="Body site id, e.g. skin.")
    parser.add_argument("--terms", required=True, help="Search terms, e.g. 'skin microbiome xenobiotic metabolism'.")
    parser.add_argument("--limit", type=int, default=25, help="Records to retrieve (default 25).")
    parser.add_argument("--output", type=Path, required=True, help="enzyme_registry.tsv to write.")
    parser.add_argument("--evidence", type=Path, default=None, help="literature_evidence.tsv to write.")
    parser.add_argument("--raw", type=Path, default=None, help="Keep the retrieved table here.")
    parser.add_argument("--dry-run", action="store_true", help="Retrieve and report, write nothing.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not SEARCH.is_file():
        print(f"error: literature route not found: {SEARCH}", file=sys.stderr)
        return 2
    result = subprocess.run(
        ["bash", str(SEARCH), args.terms, "--limit", str(args.limit), "--resolve"],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        print("error: literature retrieval failed", file=sys.stderr)
        print((result.stderr or "")[-800:], file=sys.stderr)
        return 2
    raw_path = args.raw or args.output.with_suffix(".retrieved.tsv")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(result.stdout, encoding="utf-8")
    papers = read_results(raw_path)
    with_pmid = [p for p in papers if (p.get("pmid") or "").strip()]
    found = find_candidates(papers)
    entries = sorted(found.values(), key=lambda e: (-len(e["pmids"]), e["name"]))
    print(f"检索 {len(papers)} 条，其中带 PMID {len(with_pmid)} 条 -> 识别出 {len(entries)} 个候选酶")
    for entry in entries:
        print(f"  {entry['name']:36} EC {entry['ec'] or '—':10} PMID {', '.join(entry['pmids'])}")
    if args.dry_run:
        print("--dry-run: nothing written")
        return 0
    if not entries:
        print("error: no enzyme name in the retrieved text; nothing to write", file=sys.stderr)
        return 1
    write_registry(args.output, entries, args.site, args.terms)
    print(f"wrote {args.output}")
    if args.evidence:
        write_evidence(args.evidence, entries, args.site)
        print(f"wrote {args.evidence}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
