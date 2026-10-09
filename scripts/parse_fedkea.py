#!/usr/bin/env python3
"""Parse FedKEA output files into a combined validation table.

Input files (from a local FedKEA result directory or files downloaded from the
web server) are:

- binary_result.txt: Accession, IsEnzyme, Probability
- enzyme_result_with_probability.csv: hierarchical EC prediction probabilities
- enzyme_result_with_confidence.csv: Accession, FinalResult, confidence, accepted_name, other_names
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any


def read_binary(path: Path) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    if not path.is_file():
        return result
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            if not row or not any(row.values()):
                continue
            accession = row.get("Accession", row.get("accession", "")).strip()
            if accession:
                result[accession] = {
                    "is_enzyme": row.get("IsEnzyme", row.get("is_enzyme", "")).strip(),
                    "probability": row.get("Probability", row.get("probability", "")).strip(),
                }
    return result


def read_confidence(path: Path) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    if not path.is_file():
        return result
    with path.open("r", encoding="utf-8", newline="") as handle:
        sample = handle.read(2048)
        handle.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters="\t,")
        reader = csv.DictReader(handle, dialect=dialect)
        for row in reader:
            if not row or not any(row.values()):
                continue
            accession = row.get("Accession", row.get("accession", "")).strip()
            if accession:
                result[accession] = {
                    "final_result": row.get("FinalResult", row.get("final_result", "")).strip(),
                    "confidence": row.get("confidence", "").strip(),
                    "accepted_name": row.get("accepted_name", "").strip(),
                    "other_names": row.get("other_names", "").strip(),
                }
    return result


def read_probability(path: Path) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    if not path.is_file():
        return result
    with path.open("r", encoding="utf-8", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters="\t,")
        reader = csv.DictReader(handle, dialect=dialect)
        for row in reader:
            if not row or not any(row.values()):
                continue
            accession = row.get("Accession", row.get("accession", "")).strip()
            if accession:
                result[accession] = {
                    "first": row.get("First", "").strip(),
                    "first_probability": row.get("FirstProbability", "").strip(),
                    "second": row.get("Second", "").strip(),
                    "second_probability": row.get("SecondProbability", "").strip(),
                    "third": row.get("Third", "").strip(),
                    "third_probability": row.get("ThirdProbability", "").strip(),
                    "fourth": row.get("Fourth", "").strip(),
                    "fourth_probability": row.get("FourthProbability", "").strip(),
                    "final_result": row.get("FinalResult", "").strip(),
                }
    return result


def merge_rows(
    binary: dict[str, dict[str, str]],
    prob: dict[str, dict[str, str]],
    confidence: dict[str, dict[str, str]],
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    accessions = sorted(set(binary) | set(prob) | set(confidence))
    rows: list[dict[str, Any]] = []
    binary_file = str(args.binary_result) if args.binary_result and args.binary_result.is_file() else ""
    confidence_file = str(args.confidence_csv) if args.confidence_csv and args.confidence_csv.is_file() else ""
    for accession in accessions:
        bin_row = binary.get(accession, {})
        prob_row = prob.get(accession, {})
        conf_row = confidence.get(accession, {})
        rows.append(
            {
                "protein_accession": accession,
                "fedkea_binary_result_file": binary_file,
                "fedkea_is_enzyme": bin_row.get("is_enzyme", ""),
                "fedkea_enzyme_probability": bin_row.get("probability", ""),
                "fedkea_ec_confidence_file": confidence_file,
                "fedkea_accepted_name": conf_row.get("accepted_name", ""),
                "fedkea_other_names": conf_row.get("other_names", ""),
                "fedkea_final_result": conf_row.get("final_result", prob_row.get("final_result", "")),
                "fedkea_ec_confidence": conf_row.get("confidence", ""),
                "fedkea_raw_ec_list": prob_row.get("final_result", ""),
                "fedkea_first": prob_row.get("first", ""),
                "fedkea_first_probability": prob_row.get("first_probability", ""),
                "fedkea_second": prob_row.get("second", ""),
                "fedkea_second_probability": prob_row.get("second_probability", ""),
                "fedkea_third": prob_row.get("third", ""),
                "fedkea_third_probability": prob_row.get("third_probability", ""),
                "fedkea_fourth": prob_row.get("fourth", ""),
                "fedkea_fourth_probability": prob_row.get("fourth_probability", ""),
                "fedkea_tool_version": args.tool_version,
                "fedkea_notes": "",
            }
        )
    return rows


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse FedKEA output files into one TSV.")
    parser.add_argument("--binary-result", type=Path, help="binary_result.txt from FedKEA.")
    parser.add_argument("--probability-csv", type=Path, help="enzyme_result_with_probability.csv from FedKEA.")
    parser.add_argument("--confidence-csv", type=Path, help="enzyme_result_with_confidence.csv from FedKEA.")
    parser.add_argument("--output", type=Path, required=True, help="Output fedkea_results.tsv.")
    parser.add_argument("--tool-version", default="", help="FedKEA version or repository tag.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    binary_path = args.binary_result or Path()
    probability_path = args.probability_csv or Path()
    confidence_path = args.confidence_csv or Path()
    if not binary_path.is_file() and not confidence_path.is_file():
        print("error: at least one FedKEA result file must exist", file=sys.stderr)
        return 2
    binary = read_binary(binary_path)
    probability = read_probability(probability_path)
    confidence = read_confidence(confidence_path)
    rows = merge_rows(binary, probability, confidence, args)
    fields = [
        "protein_accession",
        "fedkea_binary_result_file",
        "fedkea_is_enzyme",
        "fedkea_enzyme_probability",
        "fedkea_ec_confidence_file",
        "fedkea_accepted_name",
        "fedkea_other_names",
        "fedkea_final_result",
        "fedkea_ec_confidence",
        "fedkea_raw_ec_list",
        "fedkea_first",
        "fedkea_first_probability",
        "fedkea_second",
        "fedkea_second_probability",
        "fedkea_third",
        "fedkea_third_probability",
        "fedkea_fourth",
        "fedkea_fourth_probability",
        "fedkea_tool_version",
        "fedkea_notes",
    ]
    write_tsv(args.output, fields, rows)
    print(f"wrote {args.output} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
