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
UNIPROT_BASE = "https://rest.uniprot.org/uniprotkb/search"
# The template set is host + microbial, so the host organism is a first-class input.
DEFAULT_HOST_TAXID = 9606  # Homo sapiens

# A template must rest on experimental evidence. TrEMBL entries are marked
# "Inferred from homology" / "Predicted", and using them makes a host-like enzyme search
# look like it found nothing: the reference workflow excludes them outright.
EVIDENCE_REVIEWED = "reviewed (Swiss-Prot)"


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


def uniprot_query_url(
    ec: str,
    organism_id: int | None,
    reviewed_only: bool,
    size: int,
    extra_clause: str | None = None,
) -> str:
    """Build one UniProt search URL. Pure, so the planned queries can be tested."""
    clauses = [f"ec:{ec}"]
    if organism_id is not None:
        clauses.append(f"organism_id:{organism_id}")
    if extra_clause:
        clauses.append(extra_clause)
    if reviewed_only:
        clauses.append("reviewed:true")
    params = {"query": " AND ".join(clauses), "format": "fasta", "size": str(size)}
    return f"{UNIPROT_BASE}?{urllib.parse.urlencode(params)}"


def fetch_uniprot_references(
    ec: str,
    organism_id: int | None,
    reviewed_only: bool,
    size: int,
    target_id: str,
    group: str,
    extra_clause: str | None = None,
) -> tuple[list[dict[str, str]], str]:
    """Fetch templates from UniProt and tag them with their evidence level and group.

    `group` is `host` or `microbial`: downstream consumers (and anyone reading the TSV)
    must be able to tell a human template from a bacterial one.
    """
    url = uniprot_query_url(ec, organism_id, reviewed_only, size, extra_clause)
    fasta = ""
    last_error: Exception | None = None
    for attempt in (1, 2):
        try:
            fasta = http_get(url).decode("utf-8", errors="replace")
            last_error = None
            break
        except Exception as exc:      # transient SSL/timeout must not silently degrade the set
            last_error = exc
            if attempt == 1:
                time.sleep(3)
    if last_error is not None:
        print(f"UniProt request failed ({group}, after retry): {last_error}", file=sys.stderr)
        return [], ""
    rows: list[dict[str, str]] = []
    for record in parse_fasta(fasta):
        header = record["header"]
        accession = header.split("|")[1] if "|" in header else header.split()[0]
        parts = header.split(" OS=")
        name = parts[0].split(" ", 1)[1] if " " in parts[0] else accession
        organism = parts[1].split(" OX=")[0].strip() if len(parts) > 1 else ""
        rows.append(
            {
                "target_id": target_id,
                "reference_id": accession,
                "name": name.strip(),
                "organism": organism,
                "source": "UniProt",
                "sequence_file": "",
                "catalytic_file": "",
                "ec": ec,
                "structure_file": "",
                "uniprot": accession,
                "notes": "",
                "evidence": EVIDENCE_REVIEWED if reviewed_only else "unreviewed (TrEMBL)",
                "template_group": group,
            }
        )
    return rows, fasta


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
        "evidence",
        "template_group",
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
    parser.add_argument("--retmax", type=int, default=None, help="Maximum records to fetch per template group.")
    parser.add_argument(
        "--host-organism-id",
        type=int,
        default=None,
        help=f"Taxid whose templates count as host templates (default {DEFAULT_HOST_TAXID}, Homo sapiens).",
    )
    parser.add_argument("--no-host", action="store_true",
                        help="Skip host templates; fetch microbial templates only.")
    parser.add_argument("--include-unreviewed", action="store_true",
                        help="Also accept TrEMBL entries. Off by default: 'Inferred from homology' "
                             "templates can make a host-like enzyme search look empty.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the UniProt queries that would run for host and microbial templates.")
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

    host_taxid = args.host_organism_id if args.host_organism_id is not None else DEFAULT_HOST_TAXID
    reviewed_only = not args.include_unreviewed
    target_for_rows = sanitize_ref_id(enzyme_name or ec or "REFERENCE")

    if args.dry_run:
        if not ec:
            print("--dry-run needs --ec to build the UniProt queries")
            return 0
        print("host 模板查询（宿主自身的同类酶）:")
        print("  " + ("（--no-host：跳过）" if args.no_host
                      else uniprot_query_url(ec, host_taxid, reviewed_only, retmax)))
        print("microbial 模板查询（reviewed，再按 organism 剔除宿主条目）:")
        print("  " + uniprot_query_url(ec, None, reviewed_only, retmax,
                                          "(taxonomy_id:2 OR taxonomy_id:2157)"))
        print()
        print("两类模板分开取：微生物模板找同类酶，宿主模板判断微生物蛋白是否与人体酶同源。")
        return 0

    # Host + microbial templates, reviewed first. This ordering is the fix for a real false
    # negative: five NCBI hits for EC 3.1.4.12 were distant Aeromonas/Vibrio/Streptomyces
    # entries, and a proteome that does carry the enzyme came back with zero hits.
    if ec:
        # "microbial" must be restricted to prokaryotes. Without this clause the top reviewed
        # hits for an EC are metazoan (mouse, cow, C. elegans) and get labelled microbial.
        MICROBIAL_CLAUSE = "(taxonomy_id:2 OR taxonomy_id:2157)"
        groups: list[tuple[str, int | None, str | None]] = []
        if not args.no_host:
            groups.append(("host", host_taxid, None))
        groups.append(("microbial", None, MICROBIAL_CLAUSE))
        host_accessions: set[str] = set()
        for group, taxid, clause in groups:
            group_rows, group_fasta = fetch_uniprot_references(
                ec=ec,
                organism_id=taxid,
                reviewed_only=reviewed_only,
                size=retmax,
                target_id=target_for_rows,
                group=group,
                extra_clause=clause,
            )
            if group == "host":
                host_accessions = {row["reference_id"] for row in group_rows}
            elif host_accessions:
                group_rows = [r for r in group_rows if r["reference_id"] not in host_accessions]
            rows.extend(group_rows)
            if group_fasta:
                fasta += group_fasta
            prov.append({
                "source": "UniProt",
                "group": group,
                "query": {"ec": ec, "organism_id": taxid, "reviewed_only": reviewed_only,
                          "taxon_clause": clause},
                "record_count": len(group_rows),
            })
        if not rows:
            print("warning: UniProt returned no reviewed templates for this EC; "
                  "falling back to NCBI Protein (less precise)", file=sys.stderr)

    if not rows and (enzyme_name or ec):
        ncbi_rows, ncbi_fasta = fetch_ncbi_references(
            enzyme_name=enzyme_name,
            ec=ec,
            organism=organism,
            retmax=retmax,
        )
        for row in ncbi_rows:
            # Never let a fallback row pass as a curated template: say where it came from
            # and that its evidence level is unknown.
            row.setdefault("evidence", "")
            row["evidence"] = row["evidence"] or "not stated (NCBI Protein)"
            row["template_group"] = row.get("template_group") or "unknown"
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
