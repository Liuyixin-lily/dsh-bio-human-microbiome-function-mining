#!/usr/bin/env python3
"""Extract protein/CDS/gene/mature-protein sequences for selected candidates.

Given a structural candidates TSV and a project config mapping candidate IDs to
source .faa / .ffn / .fna files, write:
  candidate_proteins.faa
  candidate_cds.ffn
  candidate_gene_sequences.fna  (CDS locus slice from the genomic .fna when possible)
  candidate_mature_proteins.faa (SignalP-cleaved proteins, optional)
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
    parser.add_argument(
        "--signalp-tsv",
        type=pathlib.Path,
        help="Optional candidate_signal_peptides.tsv from scripts/run_signalp.py.",
    )
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
    """Return candidate_id -> {"protein_fasta": ..., "cds_fasta": ..., "fna": ..., "gbff": ..., "source_genome": ...}.

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
                            "fna": info.get("fna", info.get("genome_fasta", "")),
                            "gbff": info.get("gbff", ""),
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
        for cid, info in list(source_map.items()):
            if info.get("source_genome") == genome_name and info.get("protein_fasta"):
                continue
            if cid.startswith("WP_") and not info.get("protein_fasta") and protein_fasta:
                candidates = extract_by_id(pathlib.Path(protein_fasta), {cid})
                if cid in candidates:
                    source_map[cid] = {
                        "source_genome": genome_name,
                        "protein_fasta": protein_fasta,
                        "cds_fasta": cds_fasta,
                        "fna": genome_info.get("fna", genome_info.get("genome_fasta", "")),
                        "gbff": genome_info.get("gbff", ""),
                    }
                    continue
            if info.get("source_genome") == genome_name and not info.get("fna"):
                source_map[cid]["fna"] = genome_info.get("fna", genome_info.get("genome_fasta", ""))
    return source_map


def read_signalp(path: pathlib.Path | None) -> dict[str, dict[str, str]]:
    """Read normalized SignalP rows into candidate_id -> row."""
    if path is None or not path.is_file():
        return {}
    rows = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            cid = (row.get("candidate_id") or "").strip()
            if cid:
                rows[cid] = row
    return rows


def complement(seq: str) -> str:
    trans = str.maketrans("ACGTNacgtn", "TGCANtgcan")
    return seq.translate(trans)[::-1]


def location_spans(location: str) -> list[tuple[int, int]] | None:
    """Parse NCBI GenBank location strings like 123..456 or complement(79014..79832)."""
    if not location:
        return None
    text = location.strip()
    if text.startswith("complement(") and text.endswith(")"):
        text = text[len("complement(") : -1].strip()
    if text.startswith("join(") and text.endswith(")"):
        text = text[len("join(") : -1].strip()
    spans: list[tuple[int, int]] = []
    for part in text.split(","):
        part = part.replace("<", "").replace(">", "").strip()
        m = re.match(r"(\d+)\.\.(\d+)", part)
        if m:
            start, end = int(m.group(1)), int(m.group(2))
        elif re.fullmatch(r"\d+", part):
            start = end = int(part)
        else:
            continue
        spans.append((start, end))
    return spans or None


def load_genome_fasta(path: str | pathlib.Path) -> dict[str, str]:
    """Load a .fna into contig id (first header token) -> uppercase sequence."""
    fasta = pathlib.Path(path)
    if not fasta.is_file():
        return {}
    sequences: dict[str, str] = {}
    for header, seq in fasta_entries(fasta):
        seqid = header[1:].split()[0]
        if seqid.startswith("lcl|"):
            seqid = seqid[4:]
        sequences[seqid] = seq.upper()
    return sequences


def extract_gene_from_fna(cds_header: str, fna_path: str) -> tuple[str, str] | None:
    """Try to pull the CDS locus from genomic .fna using the [location=...] field."""
    location = ""
    m = re.search(r"\[location=([^\]]+)\]", cds_header)
    if m:
        location = m.group(1)
    if not location:
        return None
    spans = location_spans(location)
    if not spans:
        return None
    seqid = cds_header[1:].split("_cds_", 1)[0]
    if seqid.startswith("lcl|"):
        seqid = seqid[4:]
    genomes = load_genome_fasta(fna_path)
    contig = genomes.get(seqid)
    if contig is None:
        # Some RefSeq FASTA keeps only the base accession without the version suffix.
        base = seqid.split(".")[0]
        for candidate in genomes:
            if candidate == base or candidate.startswith(base + "."):
                contig = genomes[candidate]
                break
    if contig is None:
        return None
    complement_flag = location.strip().startswith("complement(")
    pieces = []
    for start, end in spans:
        if start < 1 or end > len(contig) or start > end:
            return None
        pieces.append(contig[start - 1 : end])
    seq = "".join(pieces)
    if complement_flag:
        seq = complement(seq)
    return seqid, seq


def mature_sequence(prot_seq: str, sig: dict[str, str]) -> str:
    """Return the SignalP-cleaved mature protein sequence, or empty if unknown."""
    try:
        if sig.get("mature_start") and sig.get("mature_end"):
            start = int(sig["mature_start"]) - 1
            end = int(sig["mature_end"])
        elif sig.get("signal_peptide_end"):
            # SignalP 6 `CS pos: X-Y` convention: if the signal peptide ends
            # at amino acid X, the mature protein starts at amino acid Y = X+1,
            # which is zero-based index X in the protein string.
            start = int(sig["signal_peptide_end"])
            end = len(prot_seq)
        else:
            return ""
        if start < 0 or end > len(prot_seq) or start >= end:
            return ""
        return prot_seq[start:end]
    except (ValueError, TypeError):
        return ""


def is_secreted(sig: dict[str, str]) -> bool:
    pred = (sig.get("signalp_prediction") or "").strip().lower()
    if not pred:
        return False
    return pred not in ("no", "none", "not_sec", "other", "-", "n/a")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    candidates_path = pathlib.Path(args.candidates)
    project_path = pathlib.Path(args.project)
    outdir = pathlib.Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    candidate_ids = read_candidate_ids(candidates_path)
    project = read_project(project_path)
    source_map = find_source_map(project)
    signalp = read_signalp(args.signalp_tsv)

    rows = []
    protein_all = {}
    cds_all = {}
    gene_all = {}
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

        gene_seq = cds_seq
        gene_header = cds_header
        gene_source = "cds_fasta"
        if info.get("fna"):
            fna_path = pathlib.Path(info["fna"])
            if not fna_path.is_absolute():
                fna_path = project_path.parent / fna_path
            extracted = extract_gene_from_fna(cds_header, str(fna_path))
            if extracted:
                _contig_id, gene_seq = extracted
                gene_header = cds_header
                gene_source = "genomic_fna"
        gene_all[cid] = (gene_header, gene_seq)

        def field(pattern: str, default: str = "") -> str:
            m = re.search(pattern, cds_header)
            return m.group(1) if m else default

        sig = signalp.get(cid, {})
        sec = is_secreted(sig)
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
                "gene_fai_header": gene_header[1:],
                "gene_seq_source": gene_source,
                "protein_length": len(prot_seq),
                "cds_length": len(cds_seq),
                "signalp_prediction": sig.get("signalp_prediction", ""),
                "signal_peptide_start": sig.get("signal_peptide_start", ""),
                "signal_peptide_end": sig.get("signal_peptide_end", ""),
                "mature_start": sig.get("mature_start", ""),
                "mature_end": sig.get("mature_end", ""),
                "cleavage_site": sig.get("cleavage_site", ""),
                "is_secreted": "Yes" if sec else "No",
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

    with (outdir / "candidate_gene_sequences.fna").open("w", encoding="utf-8", newline="\n") as f:
        for cid in [r["candidate_id"] for r in rows]:
            header, seq = gene_all[cid]
            f.write(header + "\n")
            for i in range(0, len(seq), 60):
                f.write(seq[i : i + 60] + "\n")

    mature_count = 0
    mature_path = outdir / "candidate_mature_proteins.faa"
    if any(is_secreted(signalp.get(cid, {})) for cid in [r["candidate_id"] for r in rows]):
        with mature_path.open("w", encoding="utf-8", newline="\n") as f:
            for cid in [r["candidate_id"] for r in rows]:
                sig = signalp.get(cid, {})
                if not is_secreted(sig):
                    continue
                mature = mature_sequence(protein_all[cid][1], sig)
                if not mature:
                    continue
                f.write(f">{cid} mature_protein signal_peptide_removed\n")
                for i in range(0, len(mature), 60):
                    f.write(mature[i : i + 60] + "\n")
                mature_count += 1
    else:
        mature_path.unlink(missing_ok=True)

    with (outdir / "candidate_gene_evidence.tsv").open("w", encoding="utf-8", newline="\n") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print("wrote", outdir)
    print("mature proteins written:", mature_count)
    for row in rows:
        print("\t".join([row["candidate_id"], row["source_genome"], row["locus_tag"], row["location"], row["protein"]]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
