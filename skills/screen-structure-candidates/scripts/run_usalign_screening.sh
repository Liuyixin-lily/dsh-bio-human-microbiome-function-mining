#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

usage() {
    cat <<'EOF'
Run US-align structure screening for all sequence candidates against a reference target.

Usage:
  run_usalign_screening.sh --target target.pdb \
    --candidate-dir candidate_structures/ --outdir out [options]

Required:
  --target FILE        Reference target structure (PDB or CIF)
  --candidate-dir DIR  Directory containing candidate PDB/CIF structure files
  --outdir DIR         Output directory

Options:
  --candidate-id TEXT  Candidate id to write into structural outputs, default value
  --template-id TEXT   Fallback template id when USalign header is not detected
  --plddt-mean FLOAT   Mean pLDDT for predicted structures, if known
  --threshold FLOAT    TM-score threshold for structure_support, default 0.5
  --tool-version TEXT  USalign version string
  -h, --help           Show this help

DEER remains a fallback only. Run it manually when US-align does not yield
enough suitable candidates, then record DEER evidence as additional rows in
structural_candidates.tsv.
EOF
}

TARGET=""
CANDIDATE_DIR=""
OUTDIR=""
CANDIDATE_ID="candidate"
TEMPLATE_ID="template"
PLDDT_MEAN=""
THRESHOLD=0.5
TOOL_VERSION=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)
            TARGET="$2"
            shift 2
            ;;
        --candidate-dir)
            CANDIDATE_DIR="$2"
            shift 2
            ;;
        --outdir)
            OUTDIR="$2"
            shift 2
            ;;
        --candidate-id)
            CANDIDATE_ID="$2"
            shift 2
            ;;
        --template-id)
            TEMPLATE_ID="$2"
            shift 2
            ;;
        --plddt-mean)
            PLDDT_MEAN="$2"
            shift 2
            ;;
        --threshold)
            THRESHOLD="$2"
            shift 2
            ;;
        --tool-version)
            TOOL_VERSION="$2"
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

if ! command -v USalign >/dev/null 2>&1; then
    echo "Required command not found: USalign" >&2
    exit 1
fi

if [[ -z "$TARGET" || -z "$CANDIDATE_DIR" || -z "$OUTDIR" ]]; then
    echo "Missing required --target, --candidate-dir, or --outdir." >&2
    usage >&2
    exit 489
fi

if [[ ! -s "$TARGET" ]]; then
    echo "Target structure file missing or empty: $TARGET" >&2
    exit 489
fi

if [[ ! -d "$CANDIDATE_DIR" ]]; then
    echo "Candidate structure directory missing: $CANDIDATE_DIR" >&2
    exit 489
fi

mkdir -p "$OUTDIR"

HITS_OUT="${OUTDIR%/}/structural_hits.tsv"
CAND_OUT="${OUTDIR%/}/structural_candidates.tsv"

TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/usalign_screen.XXXXXX")"
trap 'rm -rf "$TEMP_DIR"' EXIT

: > "$HITS_OUT"
: > "$CAND_OUT"

shopt -s nullglob
STRUCT_FILES=("$CANDIDATE_DIR"/*.pdb "$CANDIDATE_DIR"/*.cif)

if [[ ${#STRUCT_FILES[@]} -eq 0 ]]; then
    echo "No candidate structure files found in: $CANDIDATE_DIR" >&2
    exit 489
fi

for STRUCT in "${STRUCT_FILES[@]}"; do
    BASE="$(basename "$STRUCT")"
    NAME="${BASE%.*}"
    TEXT_OUT="${TEMP_DIR}/${NAME}.usalign.txt"
    HITS_PART="${TEMP_DIR}/${NAME}.hits.tsv"
    CAND_PART="${TEMP_DIR}/${NAME}.candidates.tsv"

    echo "USalign ${TARGET} ${STRUCT}"
    USalign "$TARGET" "$STRUCT" -outfmt 2 > "$TEXT_OUT"

    EXTRA_ARGS=()
    if [[ -n "$PLDDT_MEAN" ]]; then
        EXTRA_ARGS+=(--plddt-mean "$PLDDT_MEAN")
    fi
    if [[ -n "$THRESHOLD" ]]; then
        EXTRA_ARGS+=(--threshold "$THRESHOLD")
    fi
    if [[ -n "$TOOL_VERSION" ]]; then
        EXTRA_ARGS+=(--tool-version "$TOOL_VERSION")
    fi

    python3 "$ROOT/scripts/parse_usalign.py" \
        --input "$TEXT_OUT" \
        --out-hits "$HITS_PART" \
        --out-candidates "$CAND_PART" \
        --candidate-id "$CANDIDATE_ID" \
        --template-id "$TEMPLATE_ID" \
        "${EXTRA_ARGS[@]}" \
        --prediction-pdb "$STRUCT"

    if [[ -s "$HITS_PART" ]]; then
        if [[ ! -s "$HITS_OUT" ]]; then
            cp "$HITS_PART" "$HITS_OUT"
        else
            tail -n +2 "$HITS_PART" >> "$HITS_OUT"
        fi
    fi
    if [[ -s "$CAND_PART" ]]; then
        if [[ ! -s "$CAND_OUT" ]]; then
            cp "$CAND_PART" "$CAND_OUT"
        else
            tail -n +2 "$CAND_PART" >> "$CAND_OUT"
        fi
    fi
done

cat > "${OUTDIR%/}/usalign_summary.txt" <<EOF
target                 ${TARGET}
candidate_dir          ${CANDIDATE_DIR}
structural_hits        ${HITS_OUT}
structural_candidates  ${CAND_OUT}
tm_score_threshold     ${THRESHOLD}
tool_version           ${TOOL_VERSION:-unknown}
deer_fallback          only if US-align finds no sufficient candidates
EOF

echo "SUMMARY ${OUTDIR%/}/usalign_summary.txt"
