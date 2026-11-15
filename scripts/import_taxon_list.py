#!/usr/bin/env python3
"""Turn a curated per-site microbe list into the tables the pipeline consumes.

The shipped lists (`resources/taxa/oral_known_microbes.tsv`,
`skin_known_microbes.tsv`) are *taxon + genome accession + site abundance* tables.
They are not a target library — they carry no physiological process and no enzyme —
but they supply three things the library does not:

1. an authoritative per-site taxon list to replace hand-curated `focus_taxa`;
2. concrete genome accessions, so candidate genomes can be selected without a keyword
   search;
3. measured site abundance, which is a far better basis for `site_presence_score` than
   anyone's guess.

This script emits, from one such list:

- `<site>_taxa_registry.tsv` — input for `score_target_priorities.py --taxa`
- `<site>_genome_accessions.txt` — one GCF/GCA accession per line
- `<site>_unresolved_ids.tsv` — MAG/bin ids that are not NCBI accessions
- `<site>_taxa_list.provenance.json` — source, sha256, counts, mapping rules

The abundance mapping is deliberately conservative:

    High = 5, Medium = 4, Low = 3, Scarce = 2

and `No Data` / empty stays **empty** rather than becoming 1, because a site where
nobody measured abundance is not a site where the taxon is absent.

Usage:

    python3 scripts/import_taxon_list.py \\
        --list resources/taxa/oral_known_microbes.tsv --site oral \\
        --output-dir outputs/taxa

    # then rank with the curated presence values instead of guessing them
    python3 scripts/score_target_priorities.py \\
        --taxa outputs/taxa/oral_taxa_registry.tsv \\
        --genomes work/genome_search/oral.tsv --auto-score --site oral \\
        --output outputs/task/priorities
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

TAXA_FIELDS = [
    "taxon_id",
    "genus",
    "species",
    "display_name",
    "domain",
    "core_tier",
    "recommended_strain_count",
    "key_evidence_pmids",
    "key_evidence_dois",
    "rationale",
    "site_presence_score",
    "site_presence_source",
    "metabolic_plausibility_score",
    "genome_availability_score",
    "disease_site_relevance_score",
    "experimental_accessibility_score",
]

# abundance level -> site_presence_score. Anything not listed stays empty on purpose.
ABUNDANCE_SCORE = {
    "high": 5,
    "medium": 4,
    "low": 3,
    "scarce": 2,
}

ACCESSION_RE = re.compile(r"^(GC[AF])_\d+(\.\d+)?$")
ABUNDANCE_RE = re.compile(r"abundance:\s*([A-Za-z ]+?)\)?\s*$", re.IGNORECASE)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sniff_delimiter(path: Path) -> str:
    head = path.read_text(encoding="utf-8", errors="replace")[:4096]
    return "\t" if head.count("\t") >= head.count(",") else ","


def read_table(path: Path) -> tuple[list[str], list[dict[str, str]], str]:
    delimiter = sniff_delimiter(path)
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        return list(reader.fieldnames or []), list(reader), delimiter


def pick_column(headers: list[str], candidates: list[str], role: str) -> str:
    lowered = {header.strip().lower(): header for header in headers}
    for candidate in candidates:
        for header in headers:
            if header.strip().lower() == candidate.lower():
                return header
    for candidate in candidates:
        for low, header in lowered.items():
            if candidate.lower() in low:
                return header
    raise SystemExit(
        f"error: cannot find a column for {role}. Looked for {candidates}. "
        f"Available columns: {', '.join(headers)}"
    )


def parse_abundance(raw: str) -> tuple[str, int | None]:
    """Return (level_text, score). Unknown levels stay None rather than scoring low."""
    text = (raw or "").strip()
    if not text:
        return "", None
    match = ABUNDANCE_RE.search(text)
    level = (match.group(1) if match else text).strip().strip("()").strip()
    level = re.sub(r"\s+", " ", level).lower()
    if level in {"no data", "unknown", "n/a", "na", "none"}:
        return level, None
    return level, ABUNDANCE_SCORE.get(level)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def build_rows(
    rows: list[dict[str, str]],
    taxon_col: str,
    genome_col: str,
    abundance_col: str,
    site: str,
    default_abundance: str,
) -> tuple[list[dict[str, str]], list[str], list[dict[str, str]], dict[str, int]]:
    registry: list[dict[str, str]] = []
    accessions: list[str] = []
    unresolved: list[dict[str, str]] = []
    stats = {"rows": len(rows), "scored": 0, "no_abundance": 0, "unresolved": 0, "duplicates": 0}
    seen: set[str] = set()

    for row in rows:
        taxon = (row.get(taxon_col) or "").strip()
        if not taxon:
            continue
        if taxon in seen:
            stats["duplicates"] += 1
            continue
        seen.add(taxon)

        genome_id = (row.get(genome_col) or "").strip() if genome_col else ""
        if ACCESSION_RE.match(genome_id):
            if genome_id not in accessions:
                accessions.append(genome_id)
        elif genome_id:
            unresolved.append({"taxon": taxon, "genome_id": genome_id})
            stats["unresolved"] += 1

        raw_abundance = ((row.get(abundance_col) or "").strip() if abundance_col else "") or default_abundance
        level, score = parse_abundance(raw_abundance)
        if score is None:
            stats["no_abundance"] += 1
        else:
            stats["scored"] += 1

        parts = taxon.split()
        genus = parts[0] if parts else ""
        species = " ".join(parts[1:]) if len(parts) > 1 else ""
        registry.append(
            {
                "taxon_id": slugify(taxon),
                "genus": genus,
                "species": species,
                "display_name": taxon,
                "domain": "",
                "core_tier": level,
                "recommended_strain_count": "1" if genome_id else "",
                "key_evidence_pmids": "",
                "key_evidence_dois": "",
                "rationale": (
                    f"{site} 来源名单；该位点丰度 {level or '未记录'}"
                    + (f"；参考装配 {genome_id}" if genome_id else "")
                ),
                "site_presence_score": "" if score is None else str(score),
                "site_presence_source": "taxa_list" if score is not None else "",
                "metabolic_plausibility_score": "",
                "genome_availability_score": "",
                "disease_site_relevance_score": "",
                "experimental_accessibility_score": "",
            }
        )
    return registry, accessions, unresolved, stats


def write_tsv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


WGET_RE = re.compile(r"^\s*wget\s+(\S+)(?:\s+-O\s+(\S+))?\s*$")


def parse_download_cell(raw: str) -> tuple[str, str]:
    """Return (url, suggested_filename) from a URL or a `wget ... -O name` command."""
    text = (raw or "").strip()
    if not text:
        return "", ""
    match = WGET_RE.match(text)
    if match:
        return match.group(1), (match.group(2) or "")
    return text, ""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a curated per-site microbe list into taxa registry, accession list and provenance.",
    )
    parser.add_argument("--list", type=Path, required=True, help="The curated list (TSV/CSV with a header row).")
    parser.add_argument("--site", required=True, help="Body site id, e.g. oral or skin.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Where to write the outputs.")
    parser.add_argument("--taxon-col", default=None, help="Override the taxon column name.")
    parser.add_argument("--genome-col", default=None, help="Override the genome id column name (optional).")
    parser.add_argument("--abundance-col", default=None, help="Override the abundance column name (optional).")
    parser.add_argument("--download-col", default=None,
                        help="Column holding a download URL or `wget ... -O name` command (optional).")
    parser.add_argument("--inspect", action="store_true",
                        help="Show the columns and the mapping that would be inferred; write nothing.")
    parser.add_argument(
        "--default-abundance",
        default="",
        help="Applied when the abundance cell is empty; leave unset to keep it unmeasured.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.list.is_file():
        print(f"error: list not found: {args.list}", file=sys.stderr)
        return 2

    headers, rows, delimiter = read_table(args.list)
    if not headers:
        print("error: the list has no header row", file=sys.stderr)
        return 2
    taxon_col = args.taxon_col or pick_column(
        headers, ["taxon", "display_name", "species", "organism", "bacteria/host species"], "the taxon name"
    )

    def optional_column(explicit: str | None, candidates: list[str]) -> str:
        """A column that may legitimately be absent (GMPS has no accession or abundance)."""
        if explicit:
            if explicit not in headers:
                raise SystemExit(
                    f"error: requested column not in the file: {explicit!r}; available: {', '.join(headers)}"
                )
            return explicit
        lowered = {header.strip().lower(): header for header in headers}
        for candidate in candidates:
            for header in headers:
                if header.strip().lower() == candidate.lower():
                    return header
        for candidate in candidates:
            for low, header in lowered.items():
                if candidate.lower() in low:
                    return header
        return ""

    genome_col = optional_column(args.genome_col, ["genome_id", "assembly", "accession", "genome"])
    abundance_col = optional_column(
        args.abundance_col, ["abundance", "hmt_primary_body_site_w_abundance", "body_site"]
    )
    download_col = optional_column(args.download_col, ["download link", "download", "url", "link"])

    if args.inspect:
        print(f"file      : {args.list}")
        print(f"delimiter : {delimiter!r}")
        print(f"rows      : {len(rows)}")
        print("columns   : " + ", ".join(repr(h) for h in headers))
        print()
        for role, column in (
            ("物种名", taxon_col),
            ("装配号", genome_col),
            ("位点丰度", abundance_col),
            ("下载链接", download_col),
        ):
            print(f"  {role:6}: {column or '（文件中没有）'}")
        print()
        print("缺少装配号时仍是可用名单：能出物种清单与下载清单，但没有 GCF/GCA。")
        print("缺少丰度时 site_presence_score 保持空白（不当作 0 分）。")
        return 0

    registry, accessions, unresolved, stats = build_rows(
        rows, taxon_col, genome_col, abundance_col, args.site, args.default_abundance
    )
    manifest: list[dict[str, str]] = []
    if download_col:
        for row in rows:
            taxon = (row.get(taxon_col) or "").strip()
            url, filename = parse_download_cell(row.get(download_col) or "")
            if taxon and url:
                manifest.append({"taxon": taxon, "url": url, "archive": filename})

    out = args.output_dir
    registry_path = out / f"{args.site}_taxa_registry.tsv"
    accession_path = out / f"{args.site}_genome_accessions.txt"
    unresolved_path = out / f"{args.site}_unresolved_ids.tsv"
    provenance_path = out / f"{args.site}_taxa_list.provenance.json"

    write_tsv(registry_path, registry, TAXA_FIELDS)
    accession_path.parent.mkdir(parents=True, exist_ok=True)
    accession_path.write_text("".join(a + "\n" for a in accessions), encoding="utf-8")
    if unresolved:
        write_tsv(unresolved_path, unresolved, ["taxon", "genome_id"])
    manifest_path = out / f"{args.site}_download_manifest.tsv"
    if manifest:
        write_tsv(manifest_path, manifest, ["taxon", "url", "archive"])

    write_provenance = {
        "source": "user-provided curated per-site microbe list",
        "source_file": str(args.list),
        "source_sha256": sha256_of(args.list),
        "site": args.site,
        "delimiter": delimiter,
        "columns_used": {
            "taxon": taxon_col,
            "genome_id": genome_col or None,
            "abundance": abundance_col or None,
            "download": download_col or None,
        },
        "download_manifest_rows": len(manifest),
        "has_assembly_accessions": bool(accessions),
        "counts": stats,
        "accessions_written": len(accessions),
        "abundance_mapping": {
            "rule": "High=5, Medium=4, Low=3, Scarce=2",
            "not_scored": "No Data / unknown / empty stays empty (unmeasured is not absent)",
        },
        "notes": [
            "This list is a taxon census, not a target library: it carries no process and no enzyme.",
            "MAG/bin ids cannot be downloaded from NCBI by accession; they are listed separately.",
            "site_presence_score here comes from measured site abundance, not from judgement.",
        ],
    }
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path.write_text(json.dumps(write_provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"读入 {stats['rows']} 行（分隔符 {delimiter!r}）")
    print(f"列：taxon={taxon_col!r}  genome={genome_col!r}  abundance={abundance_col!r}")
    print(f"物种 {len(registry)} 个；其中 {stats['scored']} 个有丰度可打分，"
          f"{stats['no_abundance']} 个丰度缺失（保持空白，不当作 0 分）")
    print(f"可下载装配号 {len(accessions)} 个 -> {accession_path}")
    if manifest:
        print(f"逐物种下载链接 {len(manifest)} 条 -> {manifest_path}")
    if not genome_col:
        print("note: 这个文件没有装配号列 —— 出不了 GCF/GCA 清单，但物种清单与下载清单仍可用",
              file=sys.stderr)
    if not abundance_col:
        print("note: 没有丰度列 —— site_presence_score 全部留空（不当作 0 分）", file=sys.stderr)
    if unresolved:
        print(f"MAG/bin 等非 NCBI 装配号 {len(unresolved)} 个 -> {unresolved_path}"
              "（需要走基因组组装/下载的单独流程）", file=sys.stderr)
    if stats["duplicates"]:
        print(f"跳过重复物种 {stats['duplicates']} 条", file=sys.stderr)
    print(f"wrote {registry_path}")
    print(f"wrote {provenance_path}")

    if not accessions:
        print("note: 没有任何 NCBI 装配号，这个名单只能当物种清单用", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
