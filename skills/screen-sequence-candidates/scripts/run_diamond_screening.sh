#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Run DIAMOND sequence screening for host-like enzyme discovery.

Usage:
  run_diamond_screening.sh --query query.faa --db proteome.faa --outdir out [options]
  run_diamond_screening.sh --query query.faa --dmnd proteome.dmnd --outdir out [options]

Required:
  --query FILE        Template host enzyme FASTA
  --outdir DIR        Output directory for results

Database modes (choose one):
  --db FILE           Pan-proteome FASTA used to build a DIAMOND database
  --dmnd FILE         Prebuilt DIAMOND database

Options:
  --identity FLOAT    Minimum percent identity, default 20 (percent)
  --coverage FLOAT    Minimum query coverage as fraction, default 0.7
  --evalue FLOAT      Maximum E-value, default 1e-5
  --threads INT       Threads, default 8
  --max-target-seqs INT  Max alignments per query, default 50000
  -h, --help          Show this help
EOF
}

QUERY=""
DB=""
DMND=""
OUTDIR=""
IDENTITY=20
COVERAGE=0.7
EVALUE="1e-5"
THREADS="${SLURM_CPUS_PER_TASK:-8}"
MAX_TARGETS=50000

while [[ $# -gt 0 ]]; do
    case "$1" in
        --query)
            QUERY="$2"
            shift 2
            ;;
        --db)
            DB="$2"
            shift 2
            ;;
        --dmnd)
            DMND="$2"
            shift 2
            ;;
        --outdir)
            OUTDIR="$2"
            shift 2
            ;;
        --identity)
            IDENTITY="$2"
            shift 2
            ;;
        --coverage)
            COVERAGE="$2"
            shift 2
            ;;
        --evalue)
            EVALUE="$2"
            shift 2
            ;;
        --threads)
            THREADS="$2"
            shift 2
            ;;
        --max-target-seqs)
            MAX_TARGETS="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if ! command -v diamond >/dev/null 2>&1; then
    echo "Required command not found: diamond" >&2
    exit 1
fi

if [[ -z "$QUERY" || -z "$OUTDIR" ]]; then
    echo "Missing required --query or --outdir." >&2
    usage >&2
    exit 1
fi

if [[ -z "$DMND" && -z "$DB" ]]; then
    echo "Provide one of --db or --dmnd." >&2
    usage >&2
    exit 489
fi

if [[ ! -s "$QUERY" ]]; then
    echo "Query file missing or empty: $QUERY" >&2
    exit 489
fi

mkdir -p "$OUTDIR"

DMND_PATH="$DMND"
if [[ -z "$DMND_PATH" ]]; then
    DMND_PATH="${OUTDIR%/}/panproteome.dmnd"
    echo "BUILD ${DMND_PATH}"
    diamond makedb \
        --in "$DB" \
        --db "$DMND_PATH" \
        --threads "$THREADS"
fi

RAW_M8="${OUTDIR%/}/diamond_hits.m8"
ALIGNED_TSV="${OUTDIR%/}/diamond_hits.tsv"
FILTERED_TSV="${OUTDIR%/}/diamond_hits.filtered.tsv"
SUMMARY="${OUTDIR%/}/diamond_summary.txt"

echo "ALIGN ${QUERY} against ${DMND_PATH}"
diamond blastp \
    --query "$QUERY" \
    --db "$DMND_PATH" \
    --out "$RAW_M8" \
    --outfmt 6 qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore qcovhsp \
    --evalue "$EVALUE" \
    --threads "$THREADS" \
    --max-target-seqs "$MAX_TARGETS"

# Convert standard m8 to TSV with header; filtered file keeps ID/Cov passing hits.
awk -v FS='\t' -v OFS='\t' 'NR==1 {
  print "qseqid", "sseqid", "pident", "length", "mismatch", "gapopen",
        "qstart", "qend", "sstart", "send", "evalue", "bitscore", "qcovhsp"
}
NR>1 {
  print
}' "$RAW_M8" > "$ALIGNED_TSV"

awk -v FS='\t' -v OFS='\t' 'NR==1 {
  print "qseqid", "sseqid", "pident", "length", "mismatch", "gapopen",
        "qstart", "qend", "sstart", "send", "evalue", "bitscore", "qcovhsp"
}
NR>1 && $3 >= IDT && $13 >= COV {
  print
}' IDT="$IDENTITY" COV="$COVERAGE" "$RAW_M8" > "$FILTERED_TSV"

TOTAL_HITS=$(wc -l < "$RAW_M8")
FILTERED_HITS=$(( $(wc -l < "$FILTERED_TSV") - 1 ))
FILTERED_HITS=$(( FILTERED_HITS < 0 ? 0 : FILTERED_HITS ))

cat > "$SUMMARY" <<EOF
query             ${QUERY}
db                ${DMND_PATH}
min_identity_pct  ${IDENTITY}
min_coverage_frac ${COVERAGE}
max_evalue        ${EVALUE}
total_hits        ${TOTAL_HITS}
filtered_hits     ${FILTERED_HITS}
raw_m8            ${RAW_M8}
filtered_tsv      ${FILTERED_TSV}
EOF

echo "SUMMARY ${SUMMARY}"
echo "Hits passing ID>=${IDENTITY}% and qcovhsp>=${COVERAGE}: ${FILTERED_HITS}"
