#!/usr/bin/env bash
# Bakta batch genome annotation helper.
# Defaults to the full Bakta database when --db is omitted.

set -euo pipefail

BAKTA_BIN_DIR="${BAKTA_BIN_DIR:-}"
DB_FULL="${BAKTA_DB_FULL:-}"
DB_LIGHT="${BAKTA_DB_LIGHT:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REWRITE_IDS="$SCRIPT_DIR/rewrite_bakta_ids.py"

usage() {
    cat <<'EOF'
Usage:
  bakta_batch.sh --indir DIR --outdir DIR [--db full|light] [--threads N]
                 [--mode ser|par] [--par-jobs N] [--prefix-tag TAG]
                 [--force] [--log FILE] [-h]

Options:
  --indir DIR        Input directory of genome FASTA files (*.fa, *.fna)
  --outdir DIR       Output root directory
  --db full|light    Bakta database; default is full (requires BAKTA_DB_FULL/LIGHT)
  --db-path PATH     Direct path to a Bakta database; overrides --db
  --threads N        Bakta threads per genome; default 16
  --mode ser|par     ser runs sequentially; par runs concurrent jobs; default ser
  --par-jobs N       Number of concurrent Bakta jobs in par mode; default 3
  --prefix-tag TAG   Prefix for short locus tags, e.g. SPEC -> SPEC_0001
                     Final sequence IDs are rewritten to the sample name
  --force            Overwrite existing genome output directories
  --log FILE         Append script progress to this file
  -h, --help         Show this help
EOF
}

INDIR=""
OUTDIR=""
DB="$DB_FULL"
THREADS=16
MODE="ser"
PAR_JOBS=3
PREFIX_TAG="GENOME"
FORCE=0
LOG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --indir)
            INDIR="$2"; shift 2
            ;;
        --outdir)
            OUTDIR="$2"; shift 2
            ;;
        --db)
            case "$2" in
                full) DB="$DB_FULL" ;;
                light) DB="$DB_LIGHT" ;;
                *)
                    if [[ -z "$2" ]]; then
                        echo "--db requires a value (full or light)" >&2
                        exit 2
                    fi
                    echo "Unknown --db value: $2 (expected full or light)" >&2
                    exit 2
                    ;;
            esac
            shift 2
            ;;
        --db-path)
            DB="$2"; shift 2
            ;;
        --threads)
            THREADS="$2"; shift 2
            ;;
        --mode)
            MODE="$2"; shift 2
            ;;
        --par-jobs)
            PAR_JOBS="$2"; shift 2
            ;;
        --prefix-tag)
            PREFIX_TAG="$2"; shift 2
            ;;
        --force)
            FORCE=1; shift
            ;;
        --log)
            LOG="$2"; shift 2
            ;;
        -h|--help)
            usage; exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ -z "$INDIR" || -z "$OUTDIR" ]]; then
    usage >&2
    exit 2
fi

if [[ -z "${BAKTA_BIN_DIR:-}" || ! -x "$BAKTA_BIN_DIR/bakta" ]]; then
    echo "Set BAKTA_BIN_DIR to the directory containing the bakta executable." >&2
    exit 2
fi

if [[ -z "$DB" || ! -d "$DB" ]]; then
    echo "Bakta database not configured. Use --db-path PATH or set BAKTA_DB_FULL / BAKTA_DB_LIGHT." >&2
    exit 2
fi

mkdir -p "$OUTDIR"

log() {
    if [[ -n "$LOG" ]]; then
        echo "[$(date '+%F %T')] $*" | tee -a "$LOG"
    else
        echo "[$(date '+%F %T')] $*"
    fi
}

mapfile -t fastas < <(find "$INDIR" -maxdepth 1 -type f \( -name "*.fa" -o -name "*.fna" \)| sort -u)
total=${#fastas[@]}
if [[ "$total" -eq 0 ]]; then
    log "No .fa or .fna files found under $INDIR"
    exit 1
fi

log "Found $total genome files; DB=$DB; threads=$THREADS; mode=$MODE"

run_one() {
    local fa="$1"
    local idx="$2"
    local full_prefix
    local outdir
    local tag
    local bac_out

    full_prefix=$(basename "$fa" | sed -E 's/\.(fa|fna)$//')
    outdir="$OUTDIR/$full_prefix"
    tag=$(printf '%s_%04d' "$PREFIX_TAG" "$idx")

    if [[ -f "$outdir/$full_prefix.gff3" && "$FORCE" -eq 0 ]]; then
        log "[skip] $idx/$total: $full_prefix already annotated"
        return 0
    fi

    log "[start] $idx/$total: $full_prefix (tag=$tag)"
    "$BAKTA_BIN_DIR/bakta" \
        --db "$DB" \
        --threads "$THREADS" \
        --output "$outdir" \
        --prefix "$tag" \
        --locus-tag "$tag" \
        --force \
        "$fa"

    # Rename Bakta result files to the original genome name when they use the
    # short tag as filename prefix.
    while IFS= read -r -d '' f; do
        b=$(basename "$f")
        n="${b/$tag/$full_prefix}"
        if [[ "$n" != "$b" ]]; then
            mv -f "$f" "$outdir/$n"
        fi
    done < <(find "$outdir" -maxdepth 1 -type f -name "${tag}*" -print0)

    # Rewrite Bakta's internal short tag to the original sample name in
    # sequence/feature identifiers across the text output formats.
    python3 "$REWRITE_IDS" \
        --outdir "$outdir" \
        --tag "$tag" \
        --sample "$full_prefix"

    log "[done] $idx/$total: $full_prefix"
}

export -f run_one
export OUTDIR DB THREADS PREFIX_TAG FORCE LOG BAKTA_BIN_DIR REWRITE_IDS total

if [[ "$MODE" == "par" ]]; then
    printf '%s\n' "${fastas[@]}" | xargs -P "$PAR_JOBS" -n 1 -I{} bash -c 'run_one "$@"' _ {}
else
    idx=0
    for fa in "${fastas[@]}"; do
        idx=$((idx+1))
        run_one "$fa" "$idx"
    done
fi

log "Completed annotation of $total genome files with DB=$DB"
