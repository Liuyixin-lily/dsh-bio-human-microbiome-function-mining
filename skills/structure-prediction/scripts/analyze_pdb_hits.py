#!/usr/bin/env python3
"""Classify PDB DIAMOND v2 hits into direct and homology candidates."""
import os, subprocess, sys
from pathlib import Path
def require(name):
    value = os.environ.get(name)
    if not value:
        raise SystemExit("Set %s before running this script" % name)
    return value

ROOT = Path(require('STRUCTURE_PRED_ROOT'))
outdir = ROOT / 'paper_diamond/pdb_q50_s50'
hits = outdir / 'pdb_hits_q50_s50.tsv'
qmap = ROOT / 'queries/query_map.tsv'
script = Path(__file__).resolve().parents[0] / 'analyze_diamond_hits.py'

cmd = [
    sys.executable, str(script),
    '--hits', str(hits),
    '--query-map', str(qmap),
    '--source', 'PDB',
    '--out-direct', str(outdir / 'pdb_direct_best.tsv'),
    '--out-homology', str(outdir / 'pdb_homology_candidates.tsv'),
]
print('run_pdb_analyzer', ' '.join(cmd), flush=True)
subprocess.check_call(cmd)
