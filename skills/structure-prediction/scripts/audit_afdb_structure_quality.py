#!/usr/bin/env python3
"""Audit final structures produced from the direct AFDB manifest.

By default, structures with mean CA B-factor pLDDT below 60 are quarantined so
they are no longer treated as valid final outputs.
"""
import argparse
import csv
import hashlib
import os
from pathlib import Path

from afdb_utils import afdb_plddt_threshold, evaluate_afdb_payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--manifest",
        required=True,
        help="direct AFDB candidate TSV containing protein_file/protein_id",
    )
    ap.add_argument(
        "--action",
        choices=("report", "quarantine", "delete"),
        default="report",
        help="invalid final structures may be quarantined or deleted",
    )
    ap.add_argument("--min-plddt", type=float, default=None)
    args = ap.parse_args()

    threshold = args.min_plddt if args.min_plddt is not None else afdb_plddt_threshold()
    manifest = Path(args.manifest)
    rows = []
    counts = {
        "valid": 0,
        "missing": 0,
        "empty": 0,
        "low_quality": 0,
        "invalid": 0,
    }

    with manifest.open() as f:
        reader = csv.DictReader(f, delimiter="\t")
        for record in reader:
            qid = record.get("query_id", "")
            protein_id = record.get("protein_id", "")
            template_id = record.get("template_id", "")
            protein_file = record.get("protein_file", "")
            if not protein_file or not protein_id:
                continue

            final_path = Path(protein_file).parent / "structure" / f"{protein_id}.pdb"
            if not final_path.exists():
                counts["missing"] += 1
                status = "MY_MISSING"
                plddt = ""
                final_path_text = str(final_path)
            elif final_path.stat().st_size == 0:
                counts["empty"] += 1
                status = "EMPTY_STRUCTURE"
                plddt = ""
                final_path_text = str(final_path)
            else:
                passed, status, plddt_value = evaluate_afdb_payload(
                    final_path.read_bytes(), None, threshold
                )
                final_path_text = str(final_path)
                if passed:
                    counts["valid"] += 1
                    plddt = f"{plddt_value:.3f}"
                else:
                    if status in ("LOW_PLDDT", "LOW_PLDDT_API"):
                        counts["low_quality"] += 1
                    else:
                        counts["invalid"] += 1

                    if args.action == "quarantine":
                        reject_dir = final_path.parent / "structure_low_plddt"
                        reject_dir.mkdir(parents=True, exist_ok=True)
                        token = hashlib.sha1(
                            (qid + "\t" + str(final_path)).encode("utf-8")
                        ).hexdigest()[:10]
                        rejected_path = reject_dir / f"{qid}__{final_path.name}"
                        if rejected_path.exists():
                            rejected_path = reject_dir / f"{token}__{final_path.name}"
                        os.replace(final_path, rejected_path)
                        final_path_text = str(rejected_path)
                    elif args.action == "delete":
                        final_path.unlink()
                    plddt = (
                        f"{plddt_value:.3f}" if plddt_value is not None else ""
                    )

            rows.append(
                {
                    "query_id": qid,
                    "protein_id": protein_id,
                    "template_id": template_id,
                    "status": status,
                    "mean_plddt": plddt,
                    "path": final_path_text,
                }
            )

    out_log = manifest.parent / "afdb_structure_plddt_audit.tsv"
    with out_log.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "query_id",
                "protein_id",
                "template_id",
                "status",
                "mean_plddt",
                "path",
            ],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    print("threshold", threshold, "counts", counts, "log", out_log, flush=True)


if __name__ == "__main__":
    main()
