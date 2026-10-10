#!/usr/bin/env python3
"""Classify 14-column DIAMOND blastp TSV hits into direct and homology candidates.

Expected DIAMOND outfmt:
  6 qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore qlen slen
"""
import argparse, csv
from pathlib import Path

def safe_float(x):
    try:
        return float(x)
    except Exception:
        return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hits', required=True)
    ap.add_argument('--query-map', required=True)
    ap.add_argument('--source', choices=['PDB', 'AFDB'], required=True)
    ap.add_argument('--out-direct', required=True)
    ap.add_argument('--out-homology', required=True)
    ap.add_argument('--min-homology-identity', type=float, default=90.0)
    ap.add_argument('--min-homology-coverage', type=float, default=90.0)
    ap.add_argument('--min-direct-identity', type=float, default=99.9999)
    ap.add_argument('--min-direct-coverage', type=float, default=99.9999)
    args = ap.parse_args()

    hits = Path(args.hits)
    qmap_path = Path(args.query_map)
    if not hits.exists() or hits.stat().st_size == 0:
        print('no hits file:', hits, flush=True)
        return

    qmap = {}
    with qmap_path.open() as f:
        for line in f:
            fields = line.rstrip('\n').split('\t')
            if len(fields) >= 3:
                qmap[fields[0]] = (fields[1], fields[2])

    direct = {}
    homology = {}
    n_rows = 0
    n_short = 0

    with hits.open() as f:
        for line in f:
            r = line.rstrip('\n').split('\t')
            if not r:
                continue
            if r[0] in ('qseqid', 'query_id'):
                continue
            if len(r) < 14:
                n_short += 1
                continue
            qid, sid = r[0], r[1]
            if args.source == 'AFDB' and not sid.startswith('AFDB:'):
                continue
            pident = safe_float(r[2])
            if pident is None:
                continue
            try:
                qstart, qend = int(r[6]), int(r[7])
                sstart, send = int(r[8]), int(r[9])
                qlen, slen = int(r[12]), int(r[13])
            except Exception:
                continue
            if qlen <= 0 or slen <= 0 or qend < qstart or send < sstart:
                continue
            qcov = (qend - qstart + 1) / qlen * 100.0
            scov = (send - sstart + 1) / slen * 100.0
            bitscore = safe_float(r[11]) or 0.0

            if (pident < args.min_homology_identity or qcov < args.min_homology_coverage
                    or scov < args.min_homology_coverage):
                continue

            n_rows += 1
            protein_file, protein_id = qmap.get(qid, ('', ''))
            if (pident >= args.min_direct_identity and qcov >= args.min_direct_coverage
                    and scov >= args.min_direct_coverage):
                bucket = direct
                status = 'DIRECT_%s_V2' % args.source
                source = '%s_DIAMOND_100' % args.source
            else:
                bucket = homology
                status = 'HOMOLOGY_CANDIDATE_V2'
                source = '%s_HOMOLOGY_TEMPLATE' % args.source

            rank = (pident, min(qcov, scov), bitscore)
            old = bucket.get(qid)
            old_rank = None
            if old is not None:
                try:
                    old_rank = (float(old[6]), min(float(old[7]), float(old[8])), float(old[9] or 0))
                except Exception:
                    old_rank = None
            if old_rank is None or rank > old_rank:
                row = [qid, protein_file, protein_id, status, source, sid,
                       f'{pident:.3f}', f'{qcov:.3f}', f'{scov:.3f}', f'{bitscore:.3f}']
                bucket[qid] = row

    header = ['query_id', 'protein_file', 'protein_id', 'status', 'source',
              'template_id', 'pident', 'qcov', 'scov', 'bitscore']
    for path, bucket in ((Path(args.out_direct), direct), (Path(args.out_homology), homology)):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', newline='') as f:
            writer = csv.writer(f, delimiter='\t', lineterminator='\n')
            writer.writerow(header)
            for qid in sorted(bucket):
                row = bucket[qid]
                if path == Path(args.out_homology) and qid in direct:
                    continue
                writer.writerow(row)
    print('rows_kept=%d rows_short=%d source=%s direct=%d homology=%d out_direct=%s out_homology=%s' % (
        n_rows, n_short, args.source, len(direct), len(homology), args.out_direct, args.out_homology), flush=True)

if __name__ == '__main__':
    main()
