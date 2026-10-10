#!/usr/bin/env python3
"""Append two length columns to older 12-column DIAMOND outfmt 6 hits.

Reads the query FASTA and the subject FASTA (for AFDB) to compute lengths.
Writes the same hits with the qlen and slen columns appended, turning a
12-column hit TSV into a 14-column TSV.
"""
from pathlib import Path
import os, sys
def require(name):
    value = os.environ.get(name)
    if not value:
        raise SystemExit("Set %s before running this script" % name)
    return value

def build_lengths(path):
    lens = {}
    rec_id = None
    length = 0
    with path.open(errors="ignore") as f:
        for line in f:
            if line.startswith(">"):
                if rec_id is not None:
                    lens[rec_id] = length
                rec_id = line[1:].split()[0]
                length = 0
            else:
                length += len(line.strip())
        if rec_id is not None:
            lens[rec_id] = length
    return lens

def main():
    root = Path(require("STRUCTURE_PRED_ROOT"))
    hits = root / "paper_diamond/afdb_q50_s50_v2/afdb_hits_q50_s50_v2.tsv"
    query = root / "queries/all.faa"
    subject = Path(require("STRUCTURE_PRED_AFDB_FASTA"))
    out = hits.with_suffix(".full.tsv")

    qlen = build_lengths(query)
    slen = build_lengths(subject)

    n = 0
    missing = 0
    with hits.open() as fin, out.open("w") as fout:
        for line in fin:
            r = line.rstrip("\n").split("\t")
            if len(r) < 12:
                continue
            q = r[0]; s = r[1]
            if q not in qlen or s not in slen:
                missing += 1
                continue
            r.append(str(qlen[q]))
            r.append(str(slen[s]))
            fout.write("\t".join(r) + "\n")
            n += 1
    print("wrote", out, "rows", n, "missing", missing, flush=True)

if __name__ == "__main__":
    main()
