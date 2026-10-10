#!/usr/bin/env python3
"""Download AFDB direct candidates using the API pdbUrl, with gzip support.

Expected environment:
  STRUCTURE_PRED_ROOT        directory with paper_diamond/afdb_q50_s50_v2/
  STRUCTURE_PRED_AFDB_FASTA  not required for this script
"""
from pathlib import Path
import os, gzip, json, shutil, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from afdb_utils import (
    afdb_plddt_threshold,
    api_global_plddt,
    evaluate_afdb_payload,
    mean_plddt_from_pdb_text,
)
def require(name):
    value = os.environ.get(name)
    if not value:
        raise SystemExit("Set %s before running this script" % name)
    return value

ARM = Path(require("STRUCTURE_PRED_ROOT"))
CANDIDATES = ARM / "paper_diamond/afdb_q50_s50_v2/afdb_direct_best_v2.tsv"
LOG = ARM / "homology_logs/afdb_v2_direct_download.log"

lock = threading.Lock()
stats = {"total":0, "saved":0, "exists":0, "error":0, "missing_url":0, "low_quality":0}
MIN_PLDDT = afdb_plddt_threshold()
start_time = time.time()

def fetch(url, timeout=120):
    last = None
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"structure-prediction-skill/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            if getattr(e, "code", None) in (404, 400):
                time.sleep(1 + attempt)
                continue
            time.sleep(min(30, 2 ** attempt))
    raise last

def log_row(fields):
    with lock:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            f.write("\t".join(str(x) for x in fields) + "\n")

def out_path(protein_file, protein_id):
    return Path(protein_file).parent / "structure" / f"{protein_id}.pdb"

def process(row):
    if len(row) < 10:
        return
    qid, protein_file, protein_id, _status, _source, template, ident, qcov, scov, bits = row[:10]
    op = out_path(protein_file, protein_id)
    if op.exists() and op.stat().st_size > 1000:
        existing_plddt = mean_plddt_from_pdb_text(op.read_text(errors="ignore"))
        if existing_plddt is not None and existing_plddt < MIN_PLDDT:
            log_row([qid, protein_id, template, "LOW_PLDDT_EXISTS", str(op), ident, qcov, scov, "", existing_plddt])
            with lock:
                stats["low_quality"] += 1
        return
    api_id = template[len("AFDB:"):] if template.startswith("AFDB:") else template
    try:
        data = json.loads(fetch("https://alphafold.ebi.ac.uk/api/prediction/%s" % api_id, timeout=120).decode("utf-8"))
        if not data:
            log_row([qid, protein_id, template, "NO_JSON", ""])
            with lock:
                stats["missing_url"] += 1
            return
        pdb_url = data[0].get("pdbUrl", "")
        metadata_plddt = api_global_plddt(data[0])
    except Exception as e:
        log_row([qid, protein_id, template, "API_ERROR", "", ident, qcov, scov, str(e)[:120]])
        with lock:
            stats["error"] += 1
        return
    if not pdb_url:
        log_row([qid, protein_id, template, "NO_PDB_URL", ""])
        with lock:
            stats["missing_url"] += 1
        return
    try:
        raw = fetch(pdb_url, timeout=180)
        passed, quality_status, quality_value = evaluate_afdb_payload(
            raw, metadata_plddt, MIN_PLDDT
        )
        if not passed:
            log_row([qid, protein_id, template, "LOW_QUALITY", quality_status, ident, qcov, scov, pdb_url, quality_value])
            with lock:
                if quality_status in ("LOW_PLDDT", "LOW_PLDDT_API"):
                    stats["low_quality"] += 1
                else:
                    stats["error"] += 1
            return
        op.parent.mkdir(parents=True, exist_ok=True)
        tmp = op.with_suffix(".pdb.tmp")
        tmp.write_bytes(raw)
        shutil.move(str(tmp), str(op))
        log_row([qid, protein_id, template, "SAVED", str(op), ident, qcov, scov, pdb_url, quality_value])
        with lock:
            stats["saved"] += 1
    except Exception as e:
        log_row([qid, protein_id, template, "DOWNLOAD_ERROR", "", ident, qcov, scov, str(e)[:120]])
        with lock:
            stats["error"] += 1

def main():
    rows = []
    if CANDIDATES.exists():
        with CANDIDATES.open() as f:
            f.readline()
            for line in f:
                r = line.rstrip("\n").split("\t")
                if len(r) >= 10:
                    rows.append(r)
    stats["total"] = len(rows)
    print("candidate_rows", len(rows), flush=True)
    with ThreadPoolExecutor(max_workers=44) as ex:
        futs = [ex.submit(process, r) for r in rows]
        done = 0
        for fut in as_completed(futs):
            fut.result()
            done += 1
            if done % 500 == 0 or done == len(futs):
                print("done", done, stats, "secs", int(time.time()-start_time), flush=True)
    print("FINAL", "min_plddt", MIN_PLDDT, stats, flush=True)

if __name__ == "__main__":
    main()
