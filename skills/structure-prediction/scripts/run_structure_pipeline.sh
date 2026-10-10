#!/usr/bin/env bash
set -euo pipefail

# Standard structure-retrieval pipeline wrapper for the structure-prediction skill.
#
# Required environment variables:
#   STRUCTURE_PRED_ROOT        Directory containing standard subdirectories:
#                              queries/all.faa, queries/query_map.tsv,
#                              paper_diamond/... (see SKILL.md)
#   STRUCTURE_PRED_AFDB_FASTA  AFDB sequences.fasta used to build afdb.dmnd.
#
# Required arguments:
#   --pdb-db PATH
#   --afdb-db PATH
#
# Example:
#   export STRUCTURE_PRED_ROOT=/path/to/workdir
#   export STRUCTURE_PRED_AFDB_FASTA=/path/to/afdb_sequences.fasta
#   bash run_structure_pipeline.sh --pdb-db /db/pdb.dmnd --afdb-db /db/afdb.dmnd \
#       --threads 44 --model-source pdb

usage() {
  cat <<'EOF'
Usage:
  STRUCTURE_PRED_ROOT=/path/to/workdir \
  STRUCTURE_PRED_AFDB_FASTA=/path/to/afdb_sequences.fasta \
  bash scripts/run_structure_pipeline.sh \
    --pdb-db /path/to/pdb.dmnd \
    --afdb-db /path/to/afdb.dmnd \
    [--threads 44] [--model-source pdb|afdb|all|none]

model-source controls homology modeling after direct downloads:
  pdb   run PDB-only homology modeling (default)
  afdb  run AFDB-only homology modeling
  all   run PDB and AFDB homology modeling sequentially
  none  stop after direct PDB/AFDB downloads
EOF
}

PDB_DB=""
AFDB_DB=""
THREADS=44
MODEL_SOURCE="pdb"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pdb-db) PDB_DB="$2"; shift 2;;
    --afdb-db) AFDB_DB="$2"; shift 2;;
    --threads) THREADS="$2"; shift 2;;
    --model-source) MODEL_SOURCE="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 1;;
  esac
done

if [[ -z "${STRUCTURE_PRED_ROOT:-}" || -z "${STRUCTURE_PRED_AFDB_FASTA:-}" || -z "$PDB_DB" || -z "$AFDB_DB" ]]; then
  echo "Missing required env vars or arguments." >&2
  usage >&2
  exit 1
fi

ROOT="${STRUCTURE_PRED_ROOT}"
AFDB_FASTA="${STRUCTURE_PRED_AFDB_FASTA}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PDB_OUT="${ROOT}/paper_diamond/pdb_q50_s50"
AFDB_OUT="${ROOT}/paper_diamond/afdb_q50_s50_v2"

mkdir -p "${ROOT}/queries" "${ROOT}/homology_logs" "${ROOT}/homology_new" "${PDB_OUT}" "${AFDB_OUT}"

# The scripts read paths relative to $STRUCTURE_PRED_ROOT.
export STRUCTURE_PRED_ROOT
export STRUCTURE_PRED_AFDB_FASTA="$AFDB_FASTA"
export STRUCTURE_PRED_AFDB_MIN_PLDDT="${STRUCTURE_PRED_AFDB_MIN_PLDDT:-60.0}"

if [[ ! -s "${ROOT}/queries/all.faa" && -s "${ROOT}/manifests/recognized.faa.list" ]]; then
  echo "[structure-prediction] Building query manifest"
  python3 "${SCRIPT_DIR}/build_query_manifest.py"
fi

OUTFMT="6 qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore qlen slen"

echo "[structure-prediction] PDB DIAMOND search"
if ! diamond blastp --ultra-sensitive --query-cover 50 --subject-cover 50 --id 50 --iterate \
    --query "${ROOT}/queries/all.faa" --db "$PDB_DB" \
    --out "${PDB_OUT}/pdb_hits_q50_s50.tsv" \
    --outfmt "$OUTFMT" --threads "$THREADS" --max-target-seqs 200 2>/dev/null; then
  echo "[structure-prediction] WARNING: PDB search skipped or failed" >&2
fi

echo "[structure-prediction] Analyze PDB hits"
python3 "${SCRIPT_DIR}/analyze_pdb_hits.py"

echo "[structure-prediction] Direct PDB download"
python3 "${SCRIPT_DIR}/download_pdb_direct.py"

echo "[structure-prediction] AFDB DIAMOND search"
if ! diamond blastp --ultra-sensitive --query-cover 50 --subject-cover 50 --id 50 --iterate \
    --query "${ROOT}/queries/all.faa" --db "$AFDB_DB" \
    --out "${AFDB_OUT}/afdb_hits_q50_s50_v2.tsv" \
    --outfmt "$OUTFMT" --threads "$THREADS" --max-target-seqs 200 2>/dev/null; then
  echo "[structure-prediction] WARNING: AFDB search skipped or failed" >&2
fi

echo "[structure-prediction] Analyze AFDB hits"
python3 "${SCRIPT_DIR}/analyze_afdb_hits.py"

echo "[structure-prediction] Direct AFDB download"
python3 "${SCRIPT_DIR}/download_afdb_direct.py"

echo "[structure-prediction] Audit direct AFDB quality (pLDDT >= ${STRUCTURE_PRED_AFDB_MIN_PLDDT})"
if [[ -s "${AFDB_OUT}/afdb_direct_best_v2.tsv" ]]; then
  python3 "${SCRIPT_DIR}/audit_afdb_structure_quality.py" \
    --manifest "${AFDB_OUT}/afdb_direct_best_v2.tsv" --action quarantine
fi

echo "[structure-prediction] Build homology pending manifest"
python3 "${SCRIPT_DIR}/build_homology_pending.py"

case "$MODEL_SOURCE" in
  pdb)
    python3 "${SCRIPT_DIR}/run_homology_modeling.py" --manifest "${ROOT}/homology_new/homology_pending_pdb_only.tsv" --threads "$THREADS"
    ;;
  afdb)
    python3 "${SCRIPT_DIR}/run_homology_modeling.py" --manifest "${ROOT}/homology_new/homology_pending_afdb_only.tsv" --threads "$THREADS"
    ;;
  all)
    python3 "${SCRIPT_DIR}/run_homology_modeling.py" --manifest "${ROOT}/homology_new/homology_pending_pdb_only.tsv" --threads "$THREADS"
    python3 "${SCRIPT_DIR}/run_homology_modeling.py" --manifest "${ROOT}/homology_new/homology_pending_afdb_only.tsv" --threads "$THREADS"
    ;;
  none|"")
    echo "[structure-prediction] Skipping homology modeling (--model-source none)"
    ;;
  *)
    echo "Unknown --model-source: $MODEL_SOURCE" >&2
    usage >&2
    exit 1
    ;;
esac

echo "[structure-prediction] Done"
