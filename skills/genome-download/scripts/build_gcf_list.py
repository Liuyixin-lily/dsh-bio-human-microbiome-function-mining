#!/usr/bin/env python3
"""Build a GCF/GCA accession TSV from species names, taxon IDs, or a manual list.

Examples:
  python3 build_gcf_list.py --species species.txt --out gcf_list.tsv
  python3 build_gcf_list.py --manual gcf_input.txt --out gcf_list.tsv
  python3 build_gcf_list.py --taxon-id-file taxon_ids.txt --out gcf_list.tsv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable


TSV_DIALECT = "excel-tab"
NCBI_DATASETS_REPORT = "https://api.ncbi.nlm.nih.gov/datasets/v2/genome/dataset_report"
DEFAULT_FIELDS = ["assembly_accession", "organism", "strain", "ftp_path"]


def iter_input_lines(path: Path) -> Iterable[str]:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            yield line


def read_manual_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    suffix = path.suffix.lower()
    if suffix in (".tsv", ".tab", ".txt"):
        with path.open("r", encoding="utf-8", newline="", errors="replace") as handle:
            sample = handle.read(2048)
        if sample.lstrip().startswith("assembly_accession"):
            try:
                with path.open("r", encoding="utf-8", newline="", errors="replace") as handle:
                    dict_rows = list(csv.DictReader(handle, dialect=TSV_DIALECT))
                if dict_rows and dict_rows[0]:
                    for row in dict_rows:
                        acc = (row.get("assembly_accession") or row.get("accession") or "").strip()
                        if not acc or not acc.upper().startswith(("GCF", "GCA")):
                            continue
                        rows.append(
                            {
                                "assembly_accession": acc,
                                "organism": (row.get("organism") or "").strip(),
                                "strain": (row.get("strain") or "").strip(),
                                "ftp_path": (row.get("ftp_path") or "").strip(),
                            }
                        )
                    return rows
            except (csv.Error, UnicodeDecodeError):
                pass
    for line in iter_input_lines(path):
        parts = line.replace(",", "\t").replace(" ", "\t").split("\t")
        parts = [p.strip() for p in parts if p.strip()]
        if not parts:
            continue
        accession = next((p for p in parts if p.upper().startswith(("GCF", "GCA"))), "")
        if not accession:
            continue
        organism = ""
        strain = ""
        if len(parts) >= 3 and parts[0] == accession:
            organism = parts[1]
            strain = parts[2]
        elif len(parts) >= 2 and parts[0] == accession:
            organism = parts[1]
        rows.append(
            {
                "assembly_accession": accession,
                "organism": organism,
                "strain": strain,
                "ftp_path": "",
            }
        )
    return rows


def read_names(path: Path) -> list[str]:
    seen: list[str] = []
    for line in iter_input_lines(path):
        if line.lower() in {"species", "organism", "taxon", "name", "taxon_id"}:
            continue
        if line not in seen:
            seen.append(line)
    return seen


def query_ncbi(taxon: str, assembly_levels: set[str], max_per: int, refseq: bool) -> list[dict[str, str]]:
    payload: dict = {
        "taxons": [taxon],
        "filters": {},
        "page_size": max_per * 5,
    }
    if refseq:
        payload["filters"]["assembly_source"] = "RefSeq"
    else:
        payload["filters"]["assembly_source"] = "GenBank"
    if assembly_levels:
        payload["filters"]["assembly_level"] = sorted(assembly_levels)
    req = urllib.request.Request(
        NCBI_DATASETS_REPORT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    rows: list[dict[str, str]] = []
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for item in data.get("reports", []) or []:
                if not isinstance(item, dict):
                    continue
                acc = item.get("current_accession") or item.get("assembly_accession") or ""
                prefix_ok = str(acc).startswith("GCF") if refseq else str(acc).startswith("GCA")
                if not prefix_ok:
                    continue
                org = item.get("organism", {}) or {}
                infraspecific = org.get("infraspecific_names", {}) or {}
                rows.append(
                    {
                        "assembly_accession": str(acc),
                        "organism": org.get("organism_name", ""),
                        "strain": infraspecific.get("strain", "") or infraspecific.get("isolate", ""),
                        "ftp_path": "",
                    }
                )
            break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt == 3:
                print(f"WARNING: NCBI query failed for {taxon}: {exc}", file=sys.stderr)
                return []
            time.sleep(2 * attempt)
            req = urllib.request.Request(
                NCBI_DATASETS_REPORT,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
    # Keep stable order and cap per-taxon count.
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if row["assembly_accession"] in seen:
            continue
        seen.add(row["assembly_accession"])
        unique.append(row)
    return unique[:max_per]


def write_tsv(rows: list[dict[str, str]], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DEFAULT_FIELDS, dialect=TSV_DIALECT)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in DEFAULT_FIELDS})
    print(f"[accessions] wrote {len(rows)} accessions -> {out}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--species", help="plain species list, one per line")
    parser.add_argument("--taxon-id-file", help="plain taxon ID list")
    parser.add_argument("--manual", help="user-provided GCF or GCA list")
    parser.add_argument("--out", required=True, help="output TSV path")
    parser.add_argument("--max-per-taxon", type=int, default=5)
    parser.add_argument(
        "--assembly-level",
        default="complete,chromosome,scaffold",
        help="comma-separated levels: complete,chromosome,scaffold,contig",
    )
    parser.add_argument("--genbank", action="store_true", help="query GenBank/GCA instead of RefSeq/GCF")
    args = parser.parse_args(argv)

    levels = {x.strip().lower() for x in args.assembly_level.split(",") if x.strip()}

    if args.manual:
        rows = read_manual_rows(Path(args.manual))
        if not rows:
            print(f"ERROR: no GCF/GCA rows found in {args.manual}", file=sys.stderr)
            return 1
        write_tsv(rows, Path(args.out))
        return 0

    if not args.species and not args.taxon_id_file:
        print("ERROR: provide --species, --taxon-id-file, or --manual", file=sys.stderr)
        return 2

    names = read_names(Path(args.taxon_id_file)) if args.taxon_id_file else read_names(Path(args.species))
    if not names:
        print("ERROR: input list is empty", file=sys.stderr)
        return 1

    rows: list[dict[str, str]] = []
    for name in names:
        hits = query_ncbi(name, levels, args.max_per_taxon, refseq=not args.genbank)
        print(f"  {name}: {len(hits)} accessions")
        rows.extend(hits)
        time.sleep(0.3)

    if not rows:
        print("ERROR: NCBI returned no accessions; try --manual with a GCF/GCA list", file=sys.stderr)
        return 1
    write_tsv(rows, Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
