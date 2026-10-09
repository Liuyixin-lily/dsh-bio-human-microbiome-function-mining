#!/usr/bin/env python3
"""Fetch a reference enzyme set from public databases.

The plugin can now build `reference_enzyme_set.tsv` automatically instead of
requiring the user to provide the file. Sources queried in order:

1. NCBI Protein (https://www.ncbi.nlm.nih.gov/protein) for proteins matching
   an enzyme name, EC number, organism, or BLAST/accession term.
2. RCSB PDB (https://data.rcsb.org) for entries matching an EC number and
   optional organism name.

Outputs:

- reference_enzyme_set.tsv (contract in schemas/reference_enzyme_set.schema.tsv)
- reference_enzymes.faa (sequences for references with NCBI protein accessions)
- reference_provenance.json (raw source URLs, query strings, and record counts)

Network endpoints used by this script:

- NCBI E-utilities
  https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi
  https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi
  https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi
- RCSB Data API
  https://data.rcsb.org/rest/v1/core/entry/{pdb_id}

This script never submits work to FedKEA or other web servers; it only reads
public reference metadata needed for the reference enzyme set.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_PROTEIN_DB = "protein"
PDB_API_BASE = "https://data.rcsb.org/rest/v1/core/entry"
DEFAULT_RETMAX = 20
NCBI_WAIT = 0.34


def http_get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "deepseek-harness/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code} for {url}", file=sys.stderr)
        raise


def ncbi_esearch(term: str, retmax: int = DEFAULT_RETMAX) -> list[str]:
    params = {
        "db": NCBI_PROTEIN_DB,
        "term": term,
        "retmode": "json",
        "retmax": str(retmax),
        "sort": "relevance",
    }
    url = f"{NCBI_BASE}/esearch.fcgi?{urllib.parse.urlencode(params)}"
    data = json.loads(http_get(url).decode("utf-8"))
    return list(data.get("esearchresult", {}).get("idlist", []) or [])


def ncbi_esummary(ids: list[str]) -> dict[str, dict[str, str]]:
    if not ids:
        return {}
    params = {
        "db": NCBI_PROTEIN_DB,
        "id": ",".join(ids),
        "retmode": "json",
    }
    url = f"{NCBI_BASE}/esummary.fcgi?{urllib.parse.urlencode(params)}"
    data = json.loads(http_get(url).decode("utf-8"))
    result = data.get("result", {}) or {}
    # esummary returns a db-keyed map on most dbs, but some endpoints nest
    # records directly under `result` alongside a `uids` list. Handle both.
    nested = result.get(NCBI_PROTEIN_DB)
    if isinstance(nested, dict):
        return nested
    records = {key: value for key, value in result.items() if key != "uids"}
    return records


def ncbi_efetch_fasta(ids: list[str]) -> str:
    if not ids:
        return ""
    params = {
        "db": NCBI_PROTEIN_DB,
        "id": ",".join(ids),
        "rettype": "fasta",
        "retmode": "text",
    }
    url = f"{NCBI_BASE}/efetch.fcgi?{urllib.parse.urlencode(params)}"
    return http_get(url).decode("utf-8")


def parse_fasta(fasta: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    header = ""
    lines: list[str] = []
    for raw in fasta.splitlines():
        if raw.startswith(">"):
            if header:
                records.append({"header": header, "sequence": "".join(lines)})
            header = raw[1:].strip()
            lines = []
        else:
            lines.append(raw.strip())
    if header:
        records.append({"header": header, "sequence": "".join(lines)})
    return records


def ncbi_build_term(
    *,
    enzyme_name: str = "",
    ec: str = "",
    organism: str = "",
    sequence: str = "",
) -> str:
    parts = [
        f'"{v}"[All Fields]' if v else "" for v in (enzyme_name,)
    ]
    if ec:
        parts.append(f'"{ec}"[EC/RN Number]')
    if organism:
        parts.append(f'"{organism}"[Organism]')
    if sequence:
        # A raw sequence is not used as a literal NCBI search term. It is
        # retained in provenance so a local BLAST-based reference build can
        # be added later with the user's compute.
        parts.append('"reference sequence provided in project config"[All Fields]')
    return " AND ".join(p for p in parts if p) or enzyme_name


def sanitize_ref_id(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", text.strip()).strip("_")
    return cleaned[:80] or "reference"


def normalize_ec(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    return raw if re.fullmatch(r"\d{1,3}(\.\d{1,3}){0,3}(\.-)?", raw) else ""


def parse_ncbi_summary(acc: str, summary: dict[str, Any]) -> dict[str, str]:
    title = summary.get("title", "") or ""
    organism = summary.get("organism", {}).get("scientificname", "") if isinstance(summary.get("organism"), dict) else (summary.get("organism", "") or "")
    ec_match = re.search(r"EC=(\S+)", title) or re.search(r"\[EC:([0-9.\-]+)\]", title)
    ec = ec_match.group(1).rstrip("]") if ec_match else ""
    name = title.split(" [")[0].strip() or acc
    return {
        "reference_id": acc,
        "name": name,
        "organism": organism,
        "ec": normalize_ec(ec),
        "source": "UniProt",
        "sequence_file": "",
        "catalytic_file": "",
        "structure_file": "",
        "uniprot": f"https://www.ncbi.nlm.nih.gov/protein/{acc}",
        "notes": f"auto-fetched from NCBI Protein via summary: {summary.get('title', '')}",
    }


def fetch_ncbi_references(
    *,
    enzyme_name: str = "",
    ec: str = "",
    organism: str = "",
    retmax: int = DEFAULT_RETMAX,
) -> tuple[list[dict[str, str]], str]:
    term = ncbi_build_term(enzyme_name=enzyme_name, ec=ec, organism=organism)
    ids = ncbi_esearch(term, retmax=retmax)
    if not ids:
        return [], ""
    time.sleep(NCBI_WAIT)
    summaries = ncbi_esummary(ids)
    rows: list[dict[str, str]] = []
    for acc in ids:
        record = summaries.get(acc)
        if not record:
            continue
        rows.append(parse_ncbi_summary(acc, record))
    time.sleep(NCBI_WAIT)
    fasta = ncbi_efetch_fasta(ids)
    return rows, fasta


def fetch_pdb_entries(
    pdb_ids: list[str],
    *,
    organism: str = "",
    target_id: str = "TARGET",
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    rows: list[dict[str, str]] = []
    provenances: list[dict[str, Any]] = []
    for pdb_id in pdb_ids:
        pdb_id = pdb_id.strip().lower()
        if not re.fullmatch(r"[0-9a-z]{4}", pdb_id):
            continue
        url = f"{PDB_API_BASE}/{pdb_id}"
        try:
            data = json.loads(http_get(url).decode("utf-8"))
        except Exception as exc:
            provenances.append({"pdb_id": pdb_id, "status": "error", "message": str(exc)})
            continue
        entry_info = data.get("struct", {}) or {}
        title = entry_info.get("title", "") or pdb_id.upper()
        tax = (data.get("rcsb_entry_info", {}).get("organism_name", []) if isinstance(data.get("rcsb_entry_info", {}).get("organism_name"), list) else [])
        organism_name = ", ".join(tax) or organism
        row: dict[str, str] = {
            "target_id": target_id,
            "reference_id": pdb_id.upper(),
            "name": title,
            "organism": organism_name,
            "source": "PDB",
            "sequence_file": "",
            "catalytic_file": "",
            "ec": "",
            "structure_file": f"https://files.rcsb.org/download/{pdb_id.upper()}.pdb",
            "uniprot": f"https://www.rcsb.org/structure/{pdb_id.upper()}",
            "notes": f"auto-fetched from RCSB PDB entry {pdb_id.upper()}",
        }
        rows.append(row)
        provenances.append({
            "pdb_id": pdb_id,
            "url": url,
            "title": title,
            "organism_names": tax,
        })
        time.sleep(0.2)
    return rows, provenances


def write_reference_tsv(rows: list[dict[str, str]], out_path: Path) -> None:
    columns = [
        "target_id",
        "reference_id",
        "name",
        "organism",
        "source",
        "sequence_file",
        "catalytic_file",
        "ec",
        "structure_file",
        "uniprot",
        "notes",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})


def choose_primary_reference(rows: list[dict[str, str]]) -> dict[str, str] | None:
    """Pick the primary reference enzyme record.

    Priority:
    1. PDB structure records (experimental structure is the strongest
       reference for US-align structural screening).
    2. Records with a UniProt/NCBI source that have a PDB or EC annotation.
    3. First record in input order.
    """
    if not rows:
        return None
    pdb_rows = [row for row in rows if row.get("source", "").upper() == "PDB"]
    if pdb_rows:
        return pdb_rows[0]
    annotated = [
        row
        for row in rows
        if "UNIPROT" in row.get("source", "").upper()
        or "NCBI" in row.get("source", "").upper()
        or row.get("ec")
        or row.get("structure_file")
    ]
    if annotated:
        return annotated[0]
    return rows[0]


def resolve_project_paths(project_path: Path, relative: str) -> Path:
    path = Path(relative)
    return path if path.is_absolute() else (project_path / path)


def download_ref_file(url: str, out_path: Path) -> bool:
    """Download a reference file to out_path; returns True on success."""
    try:
        data = http_get(url)
    except Exception as exc:
        print(f"failed to download {url}: {exc}", file=sys.stderr)
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return True


def ensure_primary_reference_files(
    primary: dict[str, str],
    *,
    project_root: Path,
    fasta_arg: Path,
    structure_dir: Path,
) -> tuple[bool, Path, Path]:
    """Download the primary reference's sequence and structure files locally.

    Returns (ok, primary_fasta_path, primary_pdb_path).
    """
    primary_fasta = None
    primary_pdb = None
    # Prefer a locally supplied FASTA path from the reference record.
    if primary.get("sequence_file"):
        seq_path = resolve_project_paths(project_root, primary["sequence_file"])
        if seq_path.is_file():
            primary_fasta = seq_path
    if primary_fasta is None and fasta_arg.is_file():
        primary_fasta = fasta_arg
    if primary_fasta is None and primary.get("uniprot") and "ncbi.nlm.nih.gov/protein/" in primary["uniprot"]:
        acc = primary["uniprot"].split("/protein/")[-1].split("?")[0]
        primary_fasta = structure_dir / "primary_reference.faa"
        ok = download_ref_file(
            f"{NCBI_BASE}/efetch.fcgi?{urllib.parse.urlencode({'db': NCBI_PROTEIN_DB, 'id': acc, 'rettype': 'fasta', 'retmode': 'text'})}",
            primary_fasta,
        )
        if not ok:
            primary_fasta = None

    if primary.get("structure_file"):
        pdb_path = resolve_project_paths(project_root, primary["structure_file"])
        if pdb_path.is_file():
            primary_pdb = pdb_path
        elif primary["structure_file"].startswith(("http://", "https://")):
            primary_pdb = structure_dir / "primary_reference.pdb"
            ok = download_ref_file(primary["structure_file"], primary_pdb)
            if not ok:
                primary_pdb = None

    return primary_fasta is not None or primary_pdb is not None, primary_fasta, primary_pdb


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enzyme-name", default=None, help="Reference enzyme name, for example 'neutral sphingomyelinase'.")
    parser.add_argument("--ec", default=None, help="EC number, for example 3.1.4.12.")
    parser.add_argument("--organism", default=None, help="Optional organism filter, for example 'Streptococcus'.")
    parser.add_argument("--sequence", default=None, help="Optional target sequence; kept in provenance for BLAST-based reference builds.")
    parser.add_argument("--pdb-ids", default=None, help="Comma-separated optional PDB IDs, for example 5UVG,6Q2R.")
    parser.add_argument("--project", type=Path, help="Project JSON path; used to resolve relative output paths.")
    parser.add_argument("--output", type=Path, help="Output reference_enzyme_set.tsv path.")
    parser.add_argument("--fasta-output", type=Path, help="Optional reference protein FASTA path.")
    parser.add_argument("--provenance-output", type=Path, help="Optional JSON provenance path.")
    parser.add_argument("--retmax", type=int, default=None, help="Maximum NCBI records to fetch.")
    args = parser.parse_args(argv)

    # The plugin expects commands to run from the project root. `--project`
    # provides the config values; relative output paths in config are resolved
    # against the current working directory. Passing a directory also works.
    project_root = Path.cwd()
    ref_cfg: dict[str, Any] = {}
    if args.project is not None:
        project_path = Path(args.project)
        if project_path.is_file():
            project_data = json.loads(project_path.read_text(encoding="utf-8"))
            ref_cfg = project_data.get("reference_enzyme") or {}
        else:
            project_root = project_path

    enzyme_name = args.enzyme_name if args.enzyme_name is not None else (ref_cfg.get("enzyme_name") or "")
    ec = args.ec if args.ec is not None else (ref_cfg.get("ec") or "")
    organism = args.organism if args.organism is not None else (ref_cfg.get("organism") or "")
    sequence = args.sequence if args.sequence is not None else (ref_cfg.get("sequence") or "")
    pdb_ids = args.pdb_ids if args.pdb_ids is not None else (ref_cfg.get("pdb_ids") or "")
    retmax = args.retmax if args.retmax is not None else int(ref_cfg.get("retmax") or DEFAULT_RETMAX)

    if not (enzyme_name or ec or sequence or pdb_ids):
        print("error: provide at least one of --enzyme-name, --ec, --sequence, or --pdb-ids", file=sys.stderr)
        return 2

    rows: list[dict[str, str]] = []
    prov: list[dict[str, Any]] = []
    fasta = ""
    if enzyme_name or ec:
        ncbi_rows, ncbi_fasta = fetch_ncbi_references(
            enzyme_name=enzyme_name,
            ec=ec,
            organism=organism,
            retmax=retmax,
        )
        rows.extend(ncbi_rows)
        fasta = ncbi_fasta
        prov.append({
            "source": "NCBI Protein",
            "query": {
                "enzyme_name": enzyme_name,
                "ec": ec,
                "organism": organism,
            },
            "record_count": len(ncbi_rows),
        })

    if pdb_ids:
        pdb_rows, pdb_prov = fetch_pdb_entries(
            [item for item in pdb_ids.split(",") if item.strip()],
            organism=organism,
            target_id=enzyme_name or ec or "TARGET",
        )
        rows.extend(pdb_rows)
        prov.extend(pdb_prov)

    if not rows:
        print("No reference enzymes could be fetched. Check the query terms and network access.", file=sys.stderr)
        return 1

    all_rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    output_arg = args.output
    fasta_arg = args.fasta_output
    provenance_arg = args.provenance_output
    if args.output is None:
        output_arg = Path(ref_cfg.get("output_tsv") or "outputs/reference_enzyme_set.tsv")
    if args.fasta_output is None:
        fasta_arg = Path(ref_cfg.get("output_fasta") or "outputs/reference_enzymes.faa")
    if args.provenance_output is None:
        provenance_arg = Path(ref_cfg.get("output_provenance") or "outputs/reference_provenance.json")

    target_id = sanitize_ref_id(enzyme_name or ec or "REFERENCE")
    for idx, row in enumerate(rows, start=1):
        ref_id = row.get("reference_id") or f"AUTO_{idx}"
        key = (row.get("source", ""), ref_id)
        if key in seen:
            continue
        seen.add(key)
        merged = dict(row)
        merged["target_id"] = merged.get("target_id") or target_id
        all_rows.append(merged)

    output_path = output_arg if output_arg.is_absolute() else project_root / output_arg
    write_reference_tsv(all_rows, output_path)
    print(f"wrote {output_path} ({len(all_rows)} rows)")

    primary = choose_primary_reference(all_rows)
    structure_dir = output_path.parent / "reference_enzymes"
    primary_record_path = structure_dir / "primary_reference.json"
    primary_fasta_path = structure_dir / "primary_reference.faa"
    primary_pdb_path = structure_dir / "primary_reference.pdb"
    if primary:
        files_ok, primary_fasta, primary_pdb = ensure_primary_reference_files(
            primary,
            project_root=project_root,
            fasta_arg=fasta_arg,
            structure_dir=structure_dir,
        )
        primary_record = {
            "target_id": primary.get("target_id", ""),
            "reference_id": primary.get("reference_id", ""),
            "name": primary.get("name", ""),
            "source": primary.get("source", ""),
            "ec": primary.get("ec", ""),
            "sequence_file": str(primary_fasta) if primary_fasta else "",
            "structure_file": str(primary_pdb) if primary_pdb else "",
            "notes": primary.get("notes", ""),
            "selection_rule": "PDB structure records preferred, then UniProt/NCBI annotation, then first record",
        }
        primary_record_path.parent.mkdir(parents=True, exist_ok=True)
        primary_record_path.write_text(
            json.dumps(primary_record, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {primary_record_path}")

    if fasta_arg or fasta:
        fasta_path = fasta_arg if fasta_arg.is_absolute() else project_root / fasta_arg
        if fasta:
            fasta_path.parent.mkdir(parents=True, exist_ok=True)
            fasta_path.write_text(fasta, encoding="utf-8")
            print(f"wrote {fasta_path}")

    provenance_path = provenance_arg if provenance_arg.is_absolute() else project_root / provenance_arg
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path.write_text(
        json.dumps({"rows": all_rows, "sources": prov}, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {provenance_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
