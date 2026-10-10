#!/usr/bin/env python3
"""Retry the 11 DOWNLOAD_FAILED digit accessions using API pdbUrl, correct output path."""
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

ARM = Path(require('STRUCTURE_PRED_ROOT'))
CAND = ARM / 'paper_diamond/afdb_q50_s50_v2/afdb_digit_download_failed.tsv'
OUTLOG = ARM / 'homology_logs/afdb_v2_digit_retry_final.log'

lock = threading.Lock()
stats = {'total':0, 'saved':0, 'exists':0, 'error':0, 'missing_url':0, 'low_quality':0}
MIN_PLDDT = afdb_plddt_threshold()

def fetch(url, timeout=120):
    last=None
    for attempt in range(6):
        try:
            req=urllib.request.Request(url, headers={'User-Agent':'HOMD-final-retry/1.0'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last=e
            if getattr(e,'code',None) in (404,400):
                # Retry once anyway; some 400 may be transient rate limit
                time.sleep(1 + attempt)
                continue
            time.sleep(min(30,2**attempt))
    raise last

def logrow(fields):
    with lock:
        OUTLOG.parent.mkdir(parents=True, exist_ok=True)
        with OUTLOG.open('a') as f:
            f.write('\t'.join(str(x) for x in fields)+'\n')

def process(row):
    qid, protein_file, protein_id = row[0], row[1], row[2]
    template = row[5] if len(row) > 5 else ''
    ident, qcov, scov = row[6], row[7], row[8]
    op = Path(protein_file).parent / 'structure' / f'{protein_id}.pdb'
    if op.exists() and op.stat().st_size > 1000:
        existing_plddt = mean_plddt_from_pdb_text(op.read_text(errors='ignore'))
        if existing_plddt is not None and existing_plddt < MIN_PLDDT:
            logrow([qid, protein_id, template, 'LOW_PLDDT_EXISTS', str(op), existing_plddt])
            with lock:
                stats['low_quality'] += 1
        return
    api_id = template[len('AFDB:'):] if template.startswith('AFDB:') else template
    try:
        data = json.loads(fetch('https://alphafold.ebi.ac.uk/api/prediction/%s' % api_id, timeout=120).decode('utf-8'))
        if not data:
            logrow([qid, protein_id, template, 'NO_JSON', ''])
            with lock:
                stats['missing_url'] += 1
            return
        pdb_url = data[0].get('pdbUrl','')
        metadata_plddt = api_global_plddt(data[0])
    except Exception as e:
        logrow([qid, protein_id, template, 'API_ERROR', str(e)[:200]])
        with lock:
            stats['error'] += 1
        return
    if not pdb_url:
        logrow([qid, protein_id, template, 'NO_PDB_URL', ''])
        with lock:
            stats['missing_url'] += 1
        return
    try:
        raw = fetch(pdb_url, timeout=180)
        passed, quality_status, quality_value = evaluate_afdb_payload(raw, metadata_plddt, MIN_PLDDT)
        if not passed:
            logrow([qid, protein_id, template, 'LOW_QUALITY', quality_status, str(pdb_url), quality_value])
            with lock:
                if quality_status in ('LOW_PLDDT', 'LOW_PLDDT_API'):
                    stats['low_quality'] += 1
                else:
                    stats['error'] += 1
            return
        op.parent.mkdir(parents=True, exist_ok=True)
        tmp = op.with_suffix('.pdb.tmp')
        tmp.write_bytes(raw)
        shutil.move(str(tmp), str(op))
        logrow([qid, protein_id, template, 'SAVED', str(op), quality_value])
        with lock:
            stats['saved'] += 1
    except Exception as e:
        logrow([qid, protein_id, template, 'DOWNLOAD_ERROR', str(e)[:200]])
        with lock:
            stats['error'] += 1

def main():
    headers=None
    rows=[]
    with CAND.open() as f:
        headers=f.readline().rstrip('\n').split('\t')
        for line in f:
            r=line.rstrip('\n').split('\t')
            if len(r)>=10:
                rows.append(r)
    stats['total']=len(rows)
    print('rows', len(rows), flush=True)
    with ThreadPoolExecutor(max_workers=11) as ex:
        futs=[ex.submit(process, r) for r in rows]
        done=0
        for fut in as_completed(futs):
            fut.result()
            done+=1
            print('done', done, stats, flush=True)
    print('FINAL', 'min_plddt', MIN_PLDDT, stats, flush=True)

if __name__ == '__main__':
    main()
