#!/usr/bin/env python3
"""Classify AFDB DIAMOND v2 hits into direct and homology candidates."""
import os, subprocess, sys
from pathlib import Path
def require(name):
    value = os.environ.get(name)
    if not value:
        raise SystemExit("Set %s before running this script" % name)
    return value

ROOT = Path(require('STRUCTURE_PRED_ROOT'))
outdir = ROOT / 'paper_diamond/afdb_q50_s50_v2'
hits = outdir / 'afdb_hits_q50_s50_v2.tsv'
qmap = ROOT / 'queries/query_map.tsv'
script = Path(__file__).resolve().parents[0] / 'analyze_diamond_hits.py'

cmd = [
    sys.executable, str(script),
    '--hits', str(hits),
    '--query-map', str(qmap),
    '--source', 'AFDB',
    '--out-direct', str(outdir / 'afdb_direct_best_v2.tsv'),
    '--out-homology', str(outdir / 'afdb_homology_candidates_v2.tsv'),
]
print('run_afdb_analyzer', ' '.join(cmd), flush=True)
subprocess.check_call(cmd)
