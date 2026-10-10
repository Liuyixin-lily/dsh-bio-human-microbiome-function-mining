#!/usr/bin/env python3
"""Build homology-modeling pending manifests from PDB/AFDB homology candidates.

Excludes queries with an assigned direct PDB or AFDB candidate, and skips
proteins that already have a non-empty structure file.
Writes a merged manifest plus separate PDB-only and AFDB-only manifests.
"""
import csv, os
from pathlib import Path
def require(name):
    value = os.environ.get(name)
    if not value:
        raise SystemExit("Set %s before running this script" % name)
    return value

ROOT = Path(require('STRUCTURE_PRED_ROOT'))
PDB_HOMOLOGY = ROOT / 'paper_diamond/pdb_q50_s50/pdb_homology_candidates.tsv'
AFDB_HOMOLOGY = ROOT / 'paper_diamond/afdb_q50_s50_v2/afdb_homology_candidates_v2.tsv'
PDB_DIRECT = ROOT / 'paper_diamond/pdb_q50_s50/pdb_direct_best.tsv'
AFDB_DIRECT = ROOT / 'paper_diamond/afdb_q50_s50_v2/afdb_direct_best_v2.tsv'
OUT = ROOT / 'homology_new/homology_pending_q50_s50.tsv'
OUT_PDB = ROOT / 'homology_new/homology_pending_pdb_only.tsv'
OUT_AFDB = ROOT / 'homology_new/homology_pending_afdb_only.tsv'


def safe_float(x):
    try:
        return float(x)
    except Exception:
        return None


def read_direct(path):
    direct = set()
    if not path.exists():
        return direct
    with path.open() as f:
        lines = f.read().splitlines()
    if lines and lines[0].startswith('query_id'):
        lines = lines[1:]
    for line in lines:
        r = line.rstrip('\n').split('\t')
        if r and r[0]:
            direct.add(r[0])
    return direct


def read_candidates(path):
    out = {}
    if not path.exists():
        return out
    with path.open() as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            qid = row.get('query_id') or row.get('')
            if not qid:
                continue
            pident = safe_float(row.get('pident'))
            qcov = safe_float(row.get('qcov') or row.get('qcovhsp'))
            scov = safe_float(row.get('scov') or row.get('scovhsp'))
            if pident is None or qcov is None or scov is None:
                continue
            out.setdefault(qid, []).append(row)
    return out


def best_for(rows):
    def key(row):
        pident = safe_float(row.get('pident')) or 0
        qcov = safe_float(row.get('qcov') or row.get('qcovhsp')) or 0
        scov = safe_float(row.get('scov') or row.get('scovhsp')) or 0
        bits = safe_float(row.get('bitscore')) or 0
        priority = 0 if row.get('source') == 'PDB_HOMOLOGY_TEMPLATE' else 1
        return (priority, pident, min(qcov, scov), bits)
    return sorted(rows, key=key)[-1]


def main():
    candidates = {}
    for path, source in ((PDB_HOMOLOGY, 'PDB_HOMOLOGY_TEMPLATE'),
                         (AFDB_HOMOLOGY, 'AFDB_HOMOLOGY_TEMPLATE')):
        for qid, rows in read_candidates(path).items():
            for row in rows:
                row = dict(row)
                row.setdefault('source', source)
                candidates.setdefault(qid, []).append(row)

    direct = read_direct(PDB_DIRECT) | read_direct(AFDB_DIRECT)

    header = ['query_id', 'protein_file', 'protein_id', 'status', 'source',
              'template_id', 'quality', 'pident', 'qcovhsp', 'scovhsp', 'structure_path']
    rows = []
    for qid in sorted(candidates):
        if qid in direct:
            continue
        best = best_for(candidates[qid])
        protein_file = best.get('protein_file', '')
        protein_id = best.get('protein_id', '')
        if not protein_file or not protein_id:
            continue
        structure_path = Path(protein_file).parent / 'structure' / f'{protein_id}.pdb'
        if structure_path.exists() and structure_path.stat().st_size > 1000:
            continue
        quality = "identity={p:.1f}%; qcovhsp={q:.1f}%; scovhsp={s:.1f}%".format(
            p=safe_float(best.get('pident')) or 0,
            q=safe_float(best.get('qcov') or best.get('qcovhsp')) or 0,
            s=safe_float(best.get('scov') or best.get('scovhsp')) or 0)
        rows.append([qid, protein_file, protein_id, 'HOMOLOGY_PENDING',
                     best.get('source', ''), best.get('template_id', ''), quality,
                     f"{safe_float(best.get('pident')) or 0:.1f}",
                     f"{safe_float(best.get('qcov') or best.get('qcovhsp')) or 0:.1f}",
                     f"{safe_float(best.get('scov') or best.get('scovhsp')) or 0:.1f}", ''])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open('w', newline='') as f:
        w = csv.writer(f, delimiter='\t', lineterminator='\n')
        w.writerow(header)
        for r in rows:
            w.writerow(r)

    with OUT_PDB.open('w', newline='') as f:
        w = csv.writer(f, delimiter='\t', lineterminator='\n')
        w.writerow(header)
        for r in rows:
            if r[4] == 'PDB_HOMOLOGY_TEMPLATE':
                w.writerow(r)

    with OUT_AFDB.open('w', newline='') as f:
        w = csv.writer(f, delimiter='\t', lineterminator='\n')
        w.writerow(header)
        for r in rows:
            if r[4] == 'AFDB_HOMOLOGY_TEMPLATE':
                w.writerow(r)

    print('out', OUT, 'candidates_after_direct', len(rows), flush=True)


if __name__ == '__main__':
    main()
