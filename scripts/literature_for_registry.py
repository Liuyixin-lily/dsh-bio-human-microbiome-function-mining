#!/usr/bin/env python3
"""Retrieve literature per candidate so the ranking components can actually be filled.

`score_target_priorities.py` derives `site_evidence`, `assay_feasibility`, `sequence_structure` and
`disease_*` from a literature table. Producing that table was a manual chore, which is why shortlists
kept coming out with those components `missing` - not because the evidence does not exist, but because
nobody had run the lookup.

This script closes that loop: for every candidate in a registry it runs the literature route, classifies
what the abstract actually says, and writes `literature_evidence.tsv` in the schema the ranker reads.

    python3 scripts/literature_for_registry.py \
        --registry outputs/task/priorities/enzyme_registry.seed.tsv \
        --site skin --limit 6 --output outputs/task/literature_evidence.tsv

Classification is deliberately conservative:

- `direct_functional_evidence` only when the abstract mentions activity or a measurement method;
- otherwise `review`;
- `verified=yes` because the identifier was retrieved, not because the claim was checked;
- the finding is the retrieved sentence, so a reader can see what the score rests on.
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SEARCH = SCRIPT_DIR / "run_literature_search.sh"

ACTIVITY_WORDS = (
    "activity", "activities", "assay", "kinetic", "km", "kcat", "specific activity",
    "hydroly", "reduc", "oxid", "catalys", "measured", "detected", "lc-ms", "hplc",
    "fluorogenic", "colorimetric", "spectrophotometric", "in vitro",
)
STRUCTURE_WORDS = ("crystal structure", "pdb", "structure of", "structural basis", "alphafold")

UNIPROT = re.compile(
    r"\b(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})\b"
)

FIELDS = [
    "candidate_id", "protein_accession", "organism_or_strain", "evidence_type",
    "reference_type", "reference_id", "title", "first_author", "journal", "year",
    "finding", "verified", "source_search", "notes",
]


def read_registry(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [row for row in csv.DictReader(handle, delimiter="\t") if (row.get("target_id") or "").strip()]


def sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?。])\s+", text or "") if part.strip()]


def query_name(name: str) -> str:
    """Strip parentheticals and secondary names before searching.

    A registry may call an entry "azoreductase (Azo1, FMN-dependent NADPH)" or
    "alcohol dehydrogenase / cytochrome P450"; asking the literature index for that whole string
    returns nothing, which then looks like "no evidence exists".
    """
    cleaned = re.sub(r"\([^)]*\)", " ", name)
    cleaned = cleaned.split("/")[0]
    return " ".join(cleaned.split())


def word_hit(sentence: str, words: tuple[str, ...]) -> bool:
    """Match at a word boundary.

    Plain substring matching called "azoreductase" an activity statement because it contains "reduc",
    which would then promote a title-only record to functional evidence. Stems are still matched as
    prefixes so "reduc" covers reduction/reduces, but only from the start of a word.
    """
    lowered = sentence.lower()
    return any(re.search(rf"\b{re.escape(word)}\w*", lowered) for word in words)


def classify(title: str, abstract: str) -> tuple[str, str]:
    """Return (evidence_type, the sentence the row will quote)."""
    text = f"{title}. {abstract}".strip()
    for sentence in sentences(text):
        if word_hit(sentence, ACTIVITY_WORDS):
            return "direct_functional_evidence", sentence
    for sentence in sentences(text):
        if word_hit(sentence, STRUCTURE_WORDS):
            return "review", sentence
    return "review", (sentences(text)[0] if sentences(text) else title)


def search(term: str, limit: int) -> tuple[list[dict[str, str]], int, int]:
    """Return (rows, hits_parsed, pmids_resolved).

    The counts matter: a query can hit records and still resolve no identifier (NCBI timeout, rate
    limit), and reporting that as "no evidence" turns a failed lookup into a silent low score.
    """
    result = subprocess.run(
        ["bash", str(SEARCH), term, "--limit", str(limit), "--resolve"],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return [], 0, 0
    parsed = resolved = 0
    table: list[str] = []
    for line in result.stdout.splitlines():
        lowered = line.lower()
        if "hits parsed" in lowered or "pmids resolved" in lowered:
            digits = "".join(ch for ch in line.split(":")[-1] if ch.isdigit())
            value = int(digits) if digits else 0
            if "hits parsed" in lowered:
                parsed = value
            else:
                resolved = value
            continue
        table.append(line)
    if not table:
        return [], parsed, resolved
    header = table[0].split("\t")
    rows = []
    for line in table[1:]:
        cells = line.split("\t")
        rows.append({name: (cells[i] if i < len(cells) else "") for i, name in enumerate(header)})
    return rows, parsed, resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a literature_evidence.tsv for a candidate registry.")
    parser.add_argument("--registry", type=Path, required=True, help="TSV with target_id and name columns.")
    parser.add_argument("--site", required=True, help="Body site id used in the query.")
    parser.add_argument("--limit", type=int, default=6, help="Records to retrieve per candidate.")
    parser.add_argument("--output", type=Path, required=True, help="literature_evidence.tsv to write.")
    parser.add_argument("--extra-terms", default="", help="Extra query words, e.g. 'enzyme activity'.")
    parser.add_argument("--dry-run", action="store_true", help="Print the queries, retrieve nothing.")
    args = parser.parse_args(argv)

    if not SEARCH.is_file():
        print(f"error: literature route not found: {SEARCH}", file=sys.stderr)
        return 2
    candidates = read_registry(args.registry)
    if not candidates:
        print(f"error: no rows with target_id in {args.registry}", file=sys.stderr)
        return 2

    rows: list[dict[str, str]] = []
    for entry in candidates:
        target_id = (entry.get("target_id") or "").strip()
        name = query_name((entry.get("name") or entry.get("enzyme_name_en") or target_id).strip())
        ec = (entry.get("ec") or "").strip()
        term = " ".join(part for part in [name, "microbiome", args.site, ec, args.extra_terms] if part)
        if args.dry_run:
            print(f"  {target_id}: {term}")
            continue
        retrieved, parsed, resolved = search(term, args.limit)
        print(f"  {target_id}: {len(retrieved)} record(s) for {term!r}")
        if parsed and not resolved:
            print(f"  warning: {target_id}: {parsed} hit(s) but 0 identifier(s) resolved; "
                  "components that need a verified record stay missing - this is a failed lookup, "
                  "not absent evidence")
        # `sequence_structure` can only be derived when a row names a structure or an accession, and a
        # topic query almost never does. Ask for it directly every time, then drop the duplicates: the
        # alternative was a per-candidate judgement about whether the abstract "probably" mentioned one.
        seen_ids = {(record.get("pmid") or "").strip() for record in retrieved}
        extra, extra_parsed, extra_resolved = search(f"{name} crystal structure", 3)
        if extra_parsed and not extra_resolved:
            print(f"  warning: {target_id}: structure query hit {extra_parsed} record(s) but "
                  "resolved none; sequence_structure will stay missing")
        extra = [record for record in extra if (record.get("pmid") or "").strip() not in seen_ids]
        if extra:
            print(f"  {target_id}: +{len(extra)} structure-targeted record(s)")
            retrieved = retrieved + extra
        for record in retrieved:
            pmid = (record.get("pmid") or "").strip()
            if not pmid:
                continue
            evidence_type, finding = classify(record.get("title") or "", record.get("abstract") or "")
            rows.append({
                "candidate_id": target_id,
                "protein_accession": target_id,
                "organism_or_strain": args.site,
                "evidence_type": evidence_type,
                "reference_type": "PMID",
                "reference_id": pmid,
                "title": (record.get("title") or "").strip(),
                "first_author": (record.get("first_author") or "").strip(),
                "journal": (record.get("journal") or "").strip(),
                "year": (record.get("year") or "").strip(),
                "finding": finding[:400],
                "verified": "yes",
                "source_search": term,
                "notes": "retrieved by literature_for_registry.py; the quoted sentence is what the score rests on",
            })

    if args.dry_run:
        return 0
    if not rows:
        print("error: no record with a resolvable identifier; nothing written", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {args.output} ({len(rows)} row(s) for {len(candidates)} candidate(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
