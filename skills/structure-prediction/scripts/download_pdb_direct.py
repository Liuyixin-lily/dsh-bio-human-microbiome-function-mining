#!/usr/bin/env python3
"""Download direct-reuse PDB chains from the PDB direct manifest.

The manifest must be produced by analyze_pdb_hits.py / analyze_diamond_hits.py
and contain columns:
  query_id, protein_file, protein_id, status, source, template_id,
  pident, qcov, scov, bitscore

For each candidate it tries the legacy PDB coordinate file first and falls back
to mmCIF conversion with Bio.PDB when the PDB format returns 404.
"""
import io, os, shutil, sys, threading, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
def require(name):
    value = os.environ.get(name)
    if not value:
        raise SystemExit("Set %s before running this script" % name)
    return value

try:
    from Bio.PDB import MMCIFParser, PDBIO
    from Bio.PDB.PDBParser import PDBParser
except Exception as exc:  # noqa: BLE001
    sys.stderr.write('Biopython is required for PDB direct download: %s\n' % exc)
    raise

ROOT = Path(require('STRUCTURE_PRED_ROOT'))
MANIFEST = ROOT / 'paper_diamond/pdb_q50_s50/pdb_direct_best.tsv'
LOG = ROOT / 'homology_logs/pdb_v2_direct_download.log'

lock = threading.Lock()
stats = {'total': 0, 'saved_pdb': 0, 'saved_cif': 0, 'exists': 0, 'error': 0, 'missing': 0}


def fetch(url, timeout=300):
    last = None
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'structure-prediction-skill/1.0'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as exc:
            last = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (400, 403, 404):
                raise
            time.sleep(min(60, 2 ** attempt))
    raise RuntimeError('failed after retries: %s' % last)


def cif_chain_to_pdb(payload, chain_id):
    parser = MMCIFParser(QUIET=True)
    str_io = io.StringIO(payload.decode('utf-8', errors='ignore'))
    structure = parser.get_structure('entry', str_io)
    target_chain = None
    for chain in structure[0]:
        if chain_id and chain.id == chain_id:
            target_chain = chain
            break
    if target_chain is None and structure[0]:
        target_chain = structure[0][0]
    if target_chain is None:
        raise RuntimeError('no chain available in mmCIF')
    if len(target_chain.id) > 1:
        target_chain.id = 'A'
    io_pdb = PDBIO()
    io_pdb.set_structure(target_chain)
    raw = io.StringIO()
    io_pdb.save(raw)
    text = raw.getvalue().strip()
    if not text:
        raise RuntimeError('no structure converted')
    return text.encode()


def write_log(handle, fields):
    with lock:
        handle.write('\t'.join(str(x) for x in fields) + '\n')
        handle.flush()


def process(row, log_handle):
    if len(row) < 10:
        return
    qid, protein_file, protein_id, status, source, template = row[:6]
    ident, qcov, scov = (row[6:9] if len(row) > 9 else ('', '', ''))
    op = Path(protein_file).parent / 'structure' / f'{protein_id}.pdb'
    if op.exists() and op.stat().st_size > 1000:
        write_log(log_handle, [qid, protein_file, protein_id, template, 'EXISTS', str(op)])
        with lock:
            stats['exists'] += 1
        return

    parts = template.split('_')
    pdb_id = parts[0].upper() if parts else template.upper()
    chain = parts[1] if len(parts) > 1 else ''

    # Prefer legacy PDB format.
    pdb_url = f'https://files.rcsb.org/download/{pdb_id}.pdb'
    try:
        raw = fetch(pdb_url)
        if not raw.startswith((b'HEADER', b'ATOM', b'CRYST1', b'MODEL')):
            raise RuntimeError('unexpected PDB payload')
        op.parent.mkdir(parents=True, exist_ok=True)
        tmp = op.with_suffix('.pdb.tmp')
        tmp.write_bytes(raw)
        if op.exists() and op.stat().st_size > 0:
            tmp.unlink(missing_ok=True)
            write_log(log_handle, [qid, protein_file, protein_id, template, 'EXISTS_RACE', str(op)])
            with lock:
                stats['exists'] += 1
            return
        shutil.move(str(tmp), str(op))
        write_log(log_handle, [qid, protein_file, protein_id, template, 'SAVED_PDB', str(op), pdb_url])
        with lock:
            stats['saved_pdb'] += 1
        return
    except Exception as exc:
        if not (isinstance(exc, urllib.error.HTTPError) and exc.code == 404):
            write_log(log_handle, [qid, protein_file, protein_id, template, 'ERROR_PDB', str(op), exc])
            with lock:
                stats['error'] += 1
            return

    # Fallback to mmCIF conversion.
    cif_url = f'https://files.rcsb.org/download/{pdb_id}.cif'
    try:
        payload = fetch(cif_url)
        converted = cif_chain_to_pdb(payload, chain)
        op.parent.mkdir(parents=True, exist_ok=True)
        tmp = op.with_suffix('.pdb.tmp')
        tmp.write_bytes(converted)
        if op.exists() and op.stat().st_size > 967:
            tmp.unlink(missing_ok=True)
            write_log(log_handle, [qid, protein_file, protein_id, template, 'EXISTS_RACE', str(op)])
            with lock:
                stats['exists'] += 1
            return
        shutil.move(str(tmp), str(op))
        write_log(log_handle, [qid, protein_file, protein_id, template, 'SAVED_CIF_TO_PDB', str(op), cif_url])
        with lock:
            stats['saved_cif'] += 1
    except Exception as exc:
        write_log(log_handle, [qid, protein_file, protein_id, template, 'ERROR_CIF', str(op), exc])
        with lock:
            stats['error'] += 1


def main():
    rows = []
    if MANIFEST.exists():
        with MANIFEST.open() as f:
            lines = f.read().splitlines()
        if lines and lines[0].startswith('query_id'):
            lines = lines[1:]
        for line in lines:
            r = line.rstrip('\n').split('\t')
            if len(r) >= 10:
                rows.append(r)
    stats['total'] = len(rows)
    print('candidate_rows', len(rows), flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a') as log_handle:
        with ThreadPoolExecutor(max_workers=16) as ex:
            futs = [ex.submit(process, r, log_handle) for r in rows]
            done = 0
            for fut in as_completed(futs):
                fut.result()
                done += 1
                if done % 100 == 0 or done == len(futs):
                    print('done', done, stats, flush=True)
    print('FINAL', stats, flush=True)


if __name__ == '__main__':
    main()
