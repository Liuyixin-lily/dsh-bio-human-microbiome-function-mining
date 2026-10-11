#!/usr/bin/env python3
"""Extract existing source-file annotation evidence for candidate proteins.

Reads either a FASTA file where header lines carry annotation text or a GenBank
flat file where CDS features carry product, EC_number, db_xref, and GO terms.
Writes a source_feature_annotations.tsv that downstream candidate merging can
use as an extra existing-knowledge evidence chain.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Any


FIELDS = [
    "candidate_id",
    "protein_accession",
    "source_file",
    "feature_type",
    "product",
    "protein_name",
    "gene",
    "locus_tag",
    "ec_number",
    "pfam",
    "interpro",
    "tigrfam",
    "cazy",
    "kegg_orthology",
    "cog",
    "go_terms",
    "description",
    "annotation_source",
    "notes",
]


def split_header(header: str) -> dict[str, str]:
    """Split a FASTA header into accession and key=value annotation pieces."""
    tokens = header.replace("\t", " ").split()
    if not tokens:
        return {"accession": "", "description": ""}
    accession = tokens[0].lstrip(">")
    description_parts: list[str] = []
    pairs: dict[str, str] = {}
    for token in tokens[1:]:
        token = token.strip("[],()")
        if "=" in token:
            key, value = token.split("=", 1)
            pairs[key] = value
        else:
            description_parts.append(token)
    return {
        "accession": accession,
        "description": " ".join(description_parts),
        **pairs,
    }


def parse_fasta(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    current_header = ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            current_header = line[1:]
            parsed = split_header(current_header)
            rows.append(_fasta_row(parsed, path))
    return rows


def _fasta_row(parsed: dict[str, str], path: Path) -> dict[str, str]:
    description = parsed.get("description", "")
    product = parsed.get("product", parsed.get("Product", ""))
    protein_name = parsed.get("protein_name", parsed.get("protein=", ""))
    gene = parsed.get("gene", parsed.get("Gene", ""))
    locus_tag = parsed.get("locus_tag", parsed.get("locus_tag=", ""))
    ec_number = parsed.get("EC_number", parsed.get("ec_number=", ""))
    pfam = parsed.get("Pfam", parsed.get("pfam=", ""))
    interpro = parsed.get("InterPro", parsed.get("interpro=", ""))
    tigrfam = parsed.get("TIGRFAM", parsed.get("tigrfam=", ""))
    cazy = parsed.get("CAZy", parsed.get("cazy=", ""))
    kegg = parsed.get("KEGG", parsed.get("kegg_orthology=", parsed.get("KO=", "")))
    cog = parsed.get("COG", parsed.get("cog=", ""))
    go_terms = parsed.get("GO", parsed.get("go_terms=", ""))
    return {
        "candidate_id": parsed.get("candidate_id", parsed.get("accession", "")),
        "protein_accession": parsed.get("accession", ""),
        "source_file": str(path),
        "feature_type": "fasta_header",
        "product": product,
        "protein_name": protein_name,
        "gene": gene,
        "locus_tag": locus_tag,
        "ec_number": ec_number,
        "pfam": pfam,
        "interpro": interpro,
        "tigrfam": tigrfam,
        "cazy": cazy,
        "kegg_orthology": kegg,
        "cog": cog,
        "go_terms": go_terms,
        "description": description,
        "annotation_source": "fasta_header",
        "notes": "",
    }


def parse_gbff(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    current: dict[str, str] = {}
    in_cds = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if in_cds and re.match(r"^     [A-Za-z][A-Za-z0-9_]* +", line) and not line.startswith("     CDS"):
            rows.append(_gbff_row(current, path))
            in_cds = False
        if in_cds and line.startswith("ORIGIN"):
            rows.append(_gbff_row(current, path))
            in_cds = False
        if line.startswith("     CDS             "):
            if in_cds:
                rows.append(_gbff_row(current, path))
            in_cds = True
            current = {
                "protein_accession": "",
                "product": "",
                "protein_name": "",
                "gene": "",
                "locus_tag": "",
                "ec_number": "",
                "db_xref": "",
                "go_terms": "",
                "old_locus_tag": "",
                "description": "",
                "_last_qual": "",
            }
            continue
        if in_cds and line.startswith("                     /"):
            current = _parse_qualifier_line(current, line)
            continue
        if in_cds and line.startswith("                     ") and current.get("_last_qual"):
            # wrapped continuation of the previous qualifier value (no leading /)
            cont = line.strip()
            if cont and not cont.startswith("/"):
                _append_qualifier(current, current["_last_qual"], cont)
            continue
        if in_cds and line.startswith("     ") and not line.startswith("                     /"):
            current_text = line[2:].strip()
            current["description"] = (current.get("description", "") + " " + current_text).strip()
            continue
        if in_cds and not line.startswith(" "):
            rows.append(_gbff_row(current, path))
            in_cds = False
    if in_cds:
        rows.append(_gbff_row(current, path))
    return rows


def _append_qualifier(row: dict[str, str], key: str, text: str) -> None:
    """Append a value/continuation to the row field for `key`.

    Only `protein_id` maps to `protein_accession`. `old_locus_tag` is a locus
    tag, not an accession: mapping it there used to yield values like
    "AADX83_08005 WP_002468583.1", which then failed to join against candidate
    tables keyed by protein accession.
    """
    text = text.strip()
    if not text:
        return
    if key == "product":
        row["product"] = (row.get("product", "") + " " + text).strip()
        row["description"] = (row.get("description", "") + " " + text).strip()
    elif key == "gene":
        row["gene"] = (row.get("gene", "") + " " + text).strip()
    elif key == "locus_tag":
        row["locus_tag"] = (row.get("locus_tag", "") + " " + text).strip()
    elif key == "old_locus_tag":
        row["old_locus_tag"] = (row.get("old_locus_tag", "") + " " + text).strip()
    elif key == "protein_id":
        row["protein_accession"] = (row.get("protein_accession", "") + " " + text).strip()
    elif key == "EC_number":
        row["ec_number"] = (row.get("ec_number", "") + " " + text).strip()
    elif key == "GO":
        row["go_terms"] = (row.get("go_terms", "") + " " + text).strip()
    elif key == "db_xref":
        row["db_xref"] = (row.get("db_xref", "") + " " + text).strip()
    elif key == "note":
        row["description"] = (row.get("description", "") + " " + text).strip()
    # other qualifiers (inference, codon_start, transl_table, pseudo, ...) are
    # bookkeeping and are deliberately not folded into `description`.


def _parse_qualifier_line(row: dict[str, str], line: str) -> dict[str, str]:
    """Parse one `/key=value` qualifier line, tolerating wrapped values.

    GenBank wraps long values and continues them on following lines that carry
    no leading `/`. Those continuations must extend the PREVIOUS qualifier, not
    be treated as free text (which used to leak note text into `description`).
    Flag qualifiers such as `/pseudo` and `/codon_start` have no `=`, so the
    split must not be assumed to yield two parts.
    """
    qualifier = line.split("/", 1)[1]
    if "=" in qualifier:
        key, value = qualifier.split("=", 1)
    else:
        key, value = qualifier, ""
    key = key.strip()
    value = value.strip().strip('"')
    row["_last_qual"] = key
    if key == "db_xref":
        if "PFAM:" in value.upper():
            row["pfam"] = value
        elif "InterPro:" in value:
            row["interpro"] = value
        elif "TIGRFAM:" in value:
            row["tigrfam"] = value
        elif "CAZy:" in value:
            row["cazy"] = value
        elif "KO:" in value or "KEGG:" in value:
            row["kegg_orthology"] = value
        elif "COG:" in value:
            row["cog"] = value
        row["db_xref"] = (row.get("db_xref", "") + " " + value).strip()
    elif value:
        _append_qualifier(row, key, value)
    return row


def _gbff_row(row: dict[str, str], path: Path) -> dict[str, str]:
    accession = row.get("protein_accession") or row.get("locus_tag") or row.get("gene") or ""
    return {
        "candidate_id": row.get("locus_tag", row.get("gene", accession)),
        "protein_accession": accession,
        "source_file": str(path),
        "feature_type": "cds",
        "product": row.get("product", ""),
        "protein_name": row.get("product", ""),
        "gene": row.get("gene", ""),
        "locus_tag": row.get("locus_tag", ""),
        "ec_number": row.get("ec_number", ""),
        "pfam": row.get("pfam", ""),
        "interpro": row.get("interpro", ""),
        "tigrfam": row.get("tigrfam", ""),
        "cazy": row.get("cazy", ""),
        "kegg_orthology": row.get("kegg_orthology", ""),
        "cog": row.get("cog", ""),
        "go_terms": row.get("go_terms", ""),
        "description": row.get("description", ""),
        "annotation_source": "genbank_cds",
        "notes": row.get("db_xref", ""),
    }


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse .faa/.gbff source annotations into one TSV.")
    parser.add_argument("--faa", action="append", type=Path, default=[], help="FASTA file with annotation-bearing headers.")
    parser.add_argument("--gbff", action="append", type=Path, default=[], help="GenBank flat file to parse for CDS qualifiers.")
    parser.add_argument("--output", type=Path, required=True, help="Output source_feature_annotations.tsv.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.faa and not args.gbff:
        print("error: provide at least one of --faa or --gbff", file=sys.stderr)
        return 489
    rows: list[dict[str, str]] = []
    for faa in args.faa:
        if not faa.is_file():
            print(f"error: FASTA file not found: {faa}", file=sys.stderr)
            return 1
        rows.extend(parse_fasta(faa))
    for gbff in args.gbff:
        if not gbff.is_file():
            print(f"error: GenBank file not found: {gbff}", file=sys.stderr)
            return 1
        rows.extend(parse_gbff(gbff))
    write_tsv(args.output, FIELDS, rows)
    print(f"wrote {args.output} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
