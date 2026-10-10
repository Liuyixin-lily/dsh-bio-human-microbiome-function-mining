#!/usr/bin/env python3
"""Stage 1: build all.faa and query_map.tsv from recognized.faa.list.

Reads:
  $STRUCTURE_PRED_ROOT/manifests/recognized.faa.list
Writes:
  $STRUCTURE_PRED_ROOT/queries/all.faa
  $STRUCTURE_PRED_ROOT/queries/query_map.tsv
"""
from pathlib import Path
import os
def require(name):
    value = os.environ.get(name)
    if not value:
        raise SystemExit("Set %s before running this script" % name)
    return value

REPO = Path(require('STRUCTURE_PRED_ROOT'))
LIST = REPO / 'manifests/recognized.faa.list'
if not LIST.exists():
    raise SystemExit(f'Missing recognized FASTA list: {LIST}')

OUT = REPO / 'queries'
OUT.mkdir(parents=True, exist_ok=True)

recognized = [
    Path(line.strip())
    for line in LIST.read_text().splitlines()
    if line.strip()
]

query_path = OUT / 'all.faa'
map_path = OUT / 'query_map.tsv'
empty_count = 0
records = []
for protein_file in sorted(recognized):
    protein_id = None
    sequence_parts = []
    for line in protein_file.read_text().splitlines():
        if line.startswith('>'):
            sequence = ''.join(sequence_parts).upper()
            if protein_id and sequence:
                records.append((str(protein_file), protein_id, sequence))
            elif protein_id:
                empty_count += 1
            protein_id = line[1:].split()[0]
            sequence_parts = []
        else:
            sequence_parts.append(line.strip())
    sequence = ''.join(sequence_parts).upper()
    if protein_id and sequence:
        records.append((str(protein_file), protein_id, sequence))
    elif protein_id:
        empty_count += 1

with query_path.open('w') as query_handle, map_path.open('w') as map_handle:
    for index, (protein_file, protein_id, sequence) in enumerate(records, 1):
        query_id = 'q%08d' % index
        query_handle.write('>%s\n%s\n' % (query_id, sequence))
        map_handle.write('\t'.join([query_id, protein_file, protein_id]) + '\n')

print('recognized_files=%d queries=%d residues=%d skipped_nonprotein=%d' % (
    len(recognized), len(records), sum(len(r[2]) for r in records), empty_count), flush=True)
