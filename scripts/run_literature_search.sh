#!/usr/bin/env bash
# run_literature_search.sh — executable bridge from the
# `human-microbiome-function-mining` plugin to the external
# `nature-academic-search` skill.
#
# Why this exists: the plugin deliberately does not bundle a literature search
# engine. It delegates to `nature-academic-search`. That delegation used to be a
# prose-only reference, which is fragile: the agent must (a) know the skill
# exists on disk, (b) find it and (c) pick a Python interpreter new enough for
# its scripts. This wrapper removes all three failure modes.
#
# Fixes two concrete problems found in practice:
#   1. `academic_search.py` uses PEP-604 unions (`str | None`) and therefore
#      crashes on Python 3.9. This wrapper selects a >=3.10 interpreter.
#   2. OpenAlex returns titles but the decisive evidence often lives in the
#      ABSTRACT. Triaging candidates on titles alone once caused a false
#      "no literature evidence" result. `--resolve` therefore converts DOIs to
#      PMIDs and fetches full PubMed records, abstracts included, so triage
#      cannot be done from titles alone.
#
# Usage:
#   run_literature_search.sh --check
#   run_literature_search.sh "query terms" [--limit N] [--year-from YYYY] [--resolve]
#   run_literature_search.sh --author "Name" [--affiliation "..."] [--resolve]
#   run_literature_search.sh --doi 10.1016/j.chom.2022.01.004
#
# Exit codes:
#   0 success
#   2 the nature-academic-search skill or its scripts were not found
#   3 no Python >= 3.10 interpreter found
#   4 the underlying academic_search.py failed

set -euo pipefail

SKILL_DIR_CANDIDATES=(
  "${NATURE_ACADEMIC_SEARCH_DIR:-}"
  "plugins/nature-academic-search"
  "skills/nature-academic-search"
  "${HOME}/.codex/skills/nature-academic-search"
  "${HOME}/.dsh/skills/nature-academic-search"
  "${HOME}/.config/dsh/skills/nature-academic-search"
)

# ---------------------------------------------------------------- locate skill
SKILL_DIR=""
for c in "${SKILL_DIR_CANDIDATES[@]}"; do
  [ -n "$c" ] || continue
  if [ -f "$c/scripts/academic_search.py" ]; then
    SKILL_DIR="$(cd "$c" && pwd)"
    break
  fi
done

if [ -z "$SKILL_DIR" ]; then
  echo "ERROR: nature-academic-search skill not found." >&2
  echo "Searched:" >&2
  for c in "${SKILL_DIR_CANDIDATES[@]}"; do [ -n "$c" ] && echo "  - $c" >&2; done
  cat >&2 <<'EOF'

Remedy (any one):
  1. Set NATURE_ACADEMIC_SEARCH_DIR=/path/to/nature-academic-search
  2. Install the skill under ~/.codex/skills/nature-academic-search
  3. Fall back to manual search terms and paste verified citations back
     (never fabricate PMID/DOI).
EOF
  exit 2
fi

SEARCH_PY="$SKILL_DIR/scripts/academic_search.py"

# ------------------------------------------------------------ locate python>=3.10
PY_BIN=""
py_ok() {
  local p="$1"
  [ -x "$p" ] || command -v "$p" >/dev/null 2>&1 || return 1
  "$p" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 10) else 1)' 2>/dev/null
}
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# Candidate workspace roots: the plugin is usually <workspace>/plugins/<plugin>,
# but it can also be checked out standalone. Probe several plausible ancestors.
WS_CANDIDATES=()
for up in "$PLUGIN_DIR/.." "$PLUGIN_DIR/../.." "$PLUGIN_DIR/../../.." \
          "$PWD" "$PWD/.." "$PWD/../.." "${HOME}"; do
  [ -d "$up" ] && WS_CANDIDATES+=("$(cd "$up" && pwd)")
done

PY_CANDIDATES=()
[ -n "${LITERATURE_PYTHON:-}" ] && PY_CANDIDATES+=("$LITERATURE_PYTHON")
PY_CANDIDATES+=(python3.13 python3.12 python3.11 python3.10)
# venvs sitting next to a plausible workspace root
for ws in "${WS_CANDIDATES[@]}"; do
  PY_CANDIDATES+=("$ws/.venv/bin/python" "$ws/venv/bin/python")
done
# common user-level interpreters
PY_CANDIDATES+=(
  "$HOME/miniconda3/bin/python3" "$HOME/anaconda3/bin/python3"
  "$HOME/miniforge3/bin/python3" "/opt/homebrew/bin/python3"
  "/usr/local/bin/python3"
)
# last resort: every python3.x visible on PATH
if command -v compgen >/dev/null 2>&1; then
  while IFS= read -r c; do
    [ -n "$c" ] && PY_CANDIDATES+=("$c")
  done < <(compgen -c 2>/dev/null | grep -E '^python3(\.[0-9]+)?$' | sort -u)
fi
PY_CANDIDATES+=(python3)

for cand in "${PY_CANDIDATES[@]}"; do
  [ -n "$cand" ] || continue
  if py_ok "$cand"; then PY_BIN="$cand"; break; fi
done

if [ -z "$PY_BIN" ]; then
  cat >&2 <<'EOF'
ERROR: no Python >= 3.10 found.
       nature-academic-search/scripts/academic_search.py uses PEP-604 unions
       (`str | None`) and raises TypeError on Python 3.9.

The literature route is DISABLED until this is fixed. Do not report a
"no literature evidence" result while this error is unresolved.

Remedies (any one):
  1. Point at an existing interpreter:
       LITERATURE_PYTHON=/path/to/python3.12 bash scripts/run_literature_search.sh --check
  2. Create one next to the plugin or the workspace root:
       python3.12 -m venv .venv     # wrapper auto-discovers <dir>/.venv/bin/python
  3. Install a newer Python (brew install python@3.12, conda, pyenv, ...).
  4. Or skip the scripted route: search PubMed/Google Scholar manually with the
     three query shapes documented in skills/literature-evidence/SKILL.md and
     paste verified citations back. Never fabricate PMID/DOI.
EOF
  exit 3
fi

# ------------------------------------------------------------------- helpers
resolve_dois() {
  # stdin: text containing DOIs; stdout: resolved records incl. abstracts
  "$PY_BIN" "$(dirname "$0")/resolve_literature_hits.py"
}

check_only() {
  echo "skill dir : $SKILL_DIR"
  echo "search py : $SEARCH_PY"
  echo "python    : $PY_BIN ($("$PY_BIN" -V 2>&1))"
  if [ -f "$SKILL_DIR/SKILL.md" ]; then
    echo "SKILL.md  : present"
  else
    echo "SKILL.md  : MISSING (search may still work)"
  fi
  echo "status    : OK"
}

# ---------------------------------------------------------------------- main
if [ "${1:-}" = "--check" ]; then
  check_only
  exit 0
fi

if [ "$#" -eq 0 ]; then
  echo "usage: $0 --check" >&2
  echo "       $0 \"<query>\" [--limit N] [--year-from YYYY] [--resolve]" >&2
  echo "       $0 --doi <DOI> [--doi <DOI> ...]" >&2
  exit 1
fi

# ---- direct DOI resolution needs no search step -------------------------
DOI_ARGS=()
for ((i = 1; i <= $#; i++)); do
  if [ "${!i}" = "--doi" ]; then
    j=$((i + 1))
    if [ $j -gt $# ]; then
      echo "ERROR: --doi requires a value" >&2
      exit 1
    fi
    DOI_ARGS+=("--doi" "${!j}")
  fi
done
if [ "${#DOI_ARGS[@]}" -gt 0 ]; then
  "$PY_BIN" "$(dirname "$0")/resolve_literature_hits.py" "${DOI_ARGS[@]}" </dev/null
  exit $?
fi

RESOLVE=0
ARGS=()
for a in "$@"; do
  if [ "$a" = "--resolve" ]; then RESOLVE=1; else ARGS+=("$a"); fi
done

RAW="$("$PY_BIN" "$SEARCH_PY" "${ARGS[@]}" 2>&1)" || {
  echo "$RAW" >&2
  echo "ERROR: academic_search.py failed" >&2
  exit 4
}

if [ "$RESOLVE" -eq 1 ]; then
  printf '%s\n' "$RAW" | resolve_dois
else
  printf '%s\n' "$RAW"
  echo >&2
  echo "NOTE: titles alone are NOT sufficient for evidence triage." >&2
  echo "      Re-run with --resolve to fetch PMIDs and abstracts before deciding." >&2
fi
