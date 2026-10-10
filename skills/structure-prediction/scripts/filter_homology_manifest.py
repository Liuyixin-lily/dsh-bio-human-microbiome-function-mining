#!/usr/bin/env python3
"""Filter a merged homology pending manifest by template source.

Usage:
  python3 scripts/filter_homology_manifest.py \
    --manifest "$STRUCTURE_PRED_ROOT/homology_new/homology_pending_q50_s50.tsv" \
    --source PDB

  python3 scripts/filter_homology_manifest.py \
    --manifest "$STRUCTURE_PRED_ROOT/homology_new/homology_pending_q50_s50.tsv" \
    --source AFDB
"""
import argparse, csv, os
from pathlib import Path


def require(name):
    value = os.environ.get(name)
    if not value:
        raise SystemExit("Set %s before running this script" % name)
    return value


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manifest', default='')
    ap.add_argument('--out', default='')
    ap.add_argument('--source', choices=['PDB', 'AFDB'], required=True)
    args = ap.parse_args()

    if args.manifest:
        src = Path(args.manifest)
    else:
        root = Path(require('STRUCTURE_PRED_ROOT'))
        src = root / 'homology_new/homology_pending_q50_s50.tsv'

    if not src.exists():
        print('missing manifest', src)
        return

    expected_source = f'{args.source}_HOMOLOGY_TEMPLATE'
    rows = []
    with src.open() as f:
        r = csv.DictReader(f, delimiter='\t')
        fieldnames = r.fieldnames
        for row in r:
            if row.get('source') == expected_source:
                rows.append(row)

    if args.out:
        out = Path(args.out)
    else:
        suffix = 'pdb_only' if args.source == 'PDB' else 'afdb_only'
        out = src.parent / f'homology_pending_{suffix}.tsv'

    with out.open('w', newline='') as f:
        w = csv.DictWriter(f, delimiter='\t', fieldnames=fieldnames, lineterminator='\n')
        w.writeheader()
        for row in rows:
            w.writerow(row)

    print(f'{args.source.lower()}_rows', len(rows))
    print('wrote', out)

if __name__ == '__main__':
    main()
