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


def read_expected_accessions(path: Path | None) -> dict[str, str]:
    """Read an accession list or single-column table of expected candidates."""
    expected: dict[str, str] = {}
    if path is None or not path.is_file():
        return expected
    with path.open("r", encoding="utf-8", newline="") as handle:
        first_line = handle.readline().rstrip("\r\n")
        handle.seek(0)
        if "\t" in first_line or "," in first_line:
            dialect = csv.Sniffer().sniff(first_line, delimiters="\t,")
            reader = csv.DictReader(handle, dialect=dialect)
            fieldnames = reader.fieldnames or []
            id_col = None
            for candidate in ("subject_refseq", "candidate_id", "query_id", "protein_id", "id", "accession"):
                if candidate in fieldnames:
                    id_col = candidate
                    break
            if id_col is None and fieldnames:
                id_col = fieldnames[0]
            for row in reader:
                if not row or not any(row.values()):
                    continue
                cid = ""
                if id_col and row.get(id_col):
                    cid = row[id_col].strip()
                elif not id_col and row:
                    cid = list(row.values())[0].strip()
                if cid:
                    expected[cid] = row
        else:
            handle.seek(0)
            for raw in handle:
                cid = raw.strip()
                if cid:
                    expected[cid] = cid
    return expected


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


def accession_check_summary(
    actual: set[str],
    expected: set[str],
) -> tuple[str, str]:
    """Return (status, note) comparing FedKEA output accessions with expected IDs.

    FedKEA output accession can silently become "MULTISPECIES:" or a truncated
    header token when the input FASTA header is not a clean first-field
    accession. We therefore treat zero overlap as a hard error and partial
    overlap as a warning recorded in fedkea_notes.
    """
    if not expected:
        return "no_expected_input", ""
    if not (actual & expected):
        return "zero_overlap", (
            f"expected={len(expected)} actual={len(actual)} "
            f"missing={len(expected)} unexpected={len(actual)}"
        )
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if not missing and not unexpected:
        return "matched", f"accession_check=expected={len(expected)} actual={len(actual)} matched=ok"
    parts = [f"expected={len(expected)}", f"actual={len(actual)}"]
    if missing:
        parts.append("missing=" + ",".join(missing[:5]) + ("..." if len(missing) > 5 else ""))
    if unexpected:
        parts.append("unexpected=" + ",".join(unexpected[:5]) + ("..." if len(unexpected) > 5 else ""))
    if missing and not unexpected:
        return "partial_missing", ";".join(parts)
    if unexpected and not missing:
        return "partial_unexpected", ";".join(parts)
    return "partial_mismatch", ";".join(parts)


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
    parser.add_argument(
        "--expected-accessions",
        type=Path,
        help=(
            "Plain accession list or TSV/CSV with an ID column such as "
            "subject_refseq/candidate_id/query_id/protein_id/id/accession. "
            "FedKEA is only valid for the candidate subset fed into it; this "
            "file lets the parser verify that output accessions can be joined "
            "back to the expected candidates."
        ),
    )
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
    expected = read_expected_accessions(args.expected_accessions)
    actual_accessions = set(binary) | set(probability) | set(confidence)
    status, note = accession_check_summary(actual_accessions, set(expected))
    if status == "zero_overlap":
        detail = f"expected={len(expected)} actual={len(actual_accessions)}"
        print(
            "error: FedKEA output has zero accession overlap with the expected "
            f"candidate IDs ({detail}). Check that the input FASTA headers are "
            "clean accession-only first fields (for example >WP_... without "
            "'MULTISPECIES:' descriptions) and that the expected list matches "
            "the sequences actually submitted to FedKEA.",
            file=sys.stderr,
        )
        return 3
    rows = merge_rows(binary, probability, confidence, args)
    if note:
        for row in rows:
            existing = row.get("fedkea_notes") or ""
            row["fedkea_notes"] = f"{existing}; {note}".strip("; ").strip() if existing else note
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
