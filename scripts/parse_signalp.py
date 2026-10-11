#!/usr/bin/env python3
"""Parse SignalP output into a normalized plugin-ready TSV table.

SignalP 6 can write GFF3 output:

  seqid  SignalP  sig_peptide   1  475  .  +  .  ID=...;Prediction=SP
  seqid  SignalP  mature_protein 476 902 .  +  .  ID=...

The txt/short output also carries cleavage information in lines like:

  #  seqid  CS pos: 475-476  ...

Following the skin-microbiome-pipeline convention, `CS pos: <X>-<Y>` is the
cleavage-site source of truth: remove the first X amino acids so the mature
protein starts at amino acid position Y (1-based).

This parser reads GFF3 files and optionally a SignalP summary table to
capture prediction class and CS position. Each protein is written as one row
in candidate_signal_peptides.tsv.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Any


DEFAULT_FIELDNAMES = [
    "candidate_id",
    "signalp_prediction",
    "signal_peptide_start",
    "signal_peptide_end",
    "mature_start",
    "mature_end",
    "cleavage_site",
    "source_file",
    "tool_version",
]


CS_POS_RE = re.compile(r"CS pos:\s*(\d+)-(\d+)", re.IGNORECASE)


def parse_summary(path: Path) -> dict[str, dict[str, str]]:
    """Best-effort parser for SignalP 5/6 summary tables with header columns."""
    result: dict[str, dict[str, str]] = {}
    if not path.is_file():
        return result

    seen_headers = False
    fieldnames: list[str] = []
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            if line.startswith("# "):
                # Header line such as:
                # # id       prediction      SP(Sec/SPI)     CS Position
                cleaned = line[2:].strip()
                if cleaned and not cleaned.lower().startswith("pos:") and not seen_headers:
                    parts = [p.strip() for p in cleaned.split("\t") if p.strip()]
                    if len(parts) >= 2 and parts[0].lower() in ("id", "seqname", "accession"):
                        fieldnames = parts
                        seen_headers = True
                continue
            if line.startswith("#"):
                continue
            parts = line.split("\t")
            if seen_headers and len(parts) == len(fieldnames):
                rows.append(dict(zip(fieldnames, [p.strip() for p in parts])))
            else:
                # For free-form summary lines:
                # lcl|..._cds_WP_... Protein SP CS pos: 475-476 ...
                seqid_match = re.match(r"(\S+)", line)
                cs_m = CS_POS_RE.search(line)
                if seqid_match:
                    rows.append(
                        {
                            "id": seqid_match.group(1),
                            "prediction": "",
                            "cs_pos": f"{cs_m.group(1)}-{cs_m.group(2)}" if cs_m else "",
                            "raw": line,
                        }
                    )

    for row in rows:
        seqid = (
            row.get("id")
            or row.get("seqname")
            or row.get("Accession")
            or row.get("# id")
            or ""
        ).strip()
        if not seqid:
            continue
        cs_pos = row.get("cs_pos", "")
        if not cs_pos:
            cs_m = CS_POS_RE.search(row.get("raw", ""))
            if cs_m:
                cs_pos = f"{cs_m.group(1)}-{cs_m.group(2)}"
        result[seqid] = {
            "prediction": row.get("prediction", row.get("Prediction", "")).strip(),
            "cs_pos": cs_pos,
        }
    return result


def parse_gff3(path: Path, summaries: dict[str, dict[str, str]]) -> dict[str, dict[str, Any]]:
    features: dict[str, list[dict[str, str]]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 9:
                continue
            seqid, _source, feature_type, start, end, _score, _strand, _frame, attributes = parts[:9]
            seqid = seqid.strip()
            feature_type = feature_type.strip()
            start = int(start)
            end = int(end)
            attr = {}
            for item in attributes.split(";"):
                if "=" in item:
                    key, value = item.split("=", 1)
                    attr[key.strip()] = value.strip()
            features.setdefault(seqid, []).append(
                {
                    "feature_type": feature_type,
                    "start": str(start),
                    "end": str(end),
                    "prediction": attr.get("Prediction", ""),
                    "type": attr.get("Type", ""),
                }
            )

    rows: dict[str, dict[str, Any]] = {}
    for seqid, feats in features.items():
        sig = next((f for f in feats if f["feature_type"].lower() in ("sig_peptide", "signal_peptide")), None)
        mature = next((f for f in feats if f["feature_type"].lower() in ("mature_protein", "mature")), None)
        summary = summaries.get(seqid, {})
        prediction = ""
        if sig and sig.get("prediction"):
            prediction = sig["prediction"]
        else:
            prediction = summary.get("prediction", "")

        # Prefer SignalP summary `CS pos: X-Y` when present; fall back to GFF3
        # mature/signal features; optionally derive Y = signal_peptide_end + 1.
        mature_start = ""
        mature_end = ""
        cleavage_site = ""
        if sig and mature:
            mature_start = mature["start"]
            mature_end = mature["end"]
            cleavage_site = f"{sig['end']}|{mature_start}"
        elif summary.get("cs_pos"):
            cs_m = re.search(r"(\d+)-(\d+)", summary["cs_pos"])
            if cs_m:
                signal_end = cs_m.group(1)
                mature_start = cs_m.group(2)
                cleavage_site = f"{signal_end}|{mature_start}"
        elif sig:
            found = CS_POS_RE.search(summary.get("raw", ""))
            if found:
                signal_end = found.group(1)
                mature_start = found.group(2)
                cleavage_site = f"{signal_end}|{mature_start}"
            else:
                mature_start = str(int(sig["end"]) + 1)
                cleavage_site = f"{sig['end']}|{mature_start}"

        row: dict[str, Any] = {
            "candidate_id": seqid,
            "signalp_prediction": prediction,
            "signal_peptide_start": sig["start"] if sig else "",
            "signal_peptide_end": sig["end"] if sig else "",
            "mature_start": mature_start,
            "mature_end": mature_end,
            "cleavage_site": cleavage_site,
            "source_file": str(path),
            "tool_version": "SignalP",
        }
        rows[seqid] = row
    return rows


def write_output(rows: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(DEFAULT_FIELDNAMES)
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse SignalP GFF3/summary output into a plugin table.")
    parser.add_argument("--gff3", type=Path, help="SignalP GFF3 output file.")
    parser.add_argument("--summary", type=Path, help="Optional SignalP summary txt file (best effort).")
    parser.add_argument("--output", required=True, type=Path, help="Output TSV path.")
    parser.add_argument("--tool-version", default="SignalP", help="SignalP version or repository tag.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.gff3 is None:
        print("--gff3 is required when parsing SignalP output directly", file=sys.stderr)
        return 2
    summaries = parse_summary(args.summary) if args.summary else {}
    rows = parse_gff3(args.gff3, summaries)
    output_rows = []
    for seqid in sorted(rows):
        row = rows[seqid]
        row["tool_version"] = args.tool_version
        output_rows.append(row)
    write_output(output_rows, args.output)
    print(f"wrote {args.output} ({len(output_rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
