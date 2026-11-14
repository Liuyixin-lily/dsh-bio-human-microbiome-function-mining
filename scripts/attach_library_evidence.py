#!/usr/bin/env python3
"""Attach retrieved literature to library entries — the only way an entry becomes verified.

`build_library_domain.py --build` deliberately refuses specs that carry identifiers and writes
every entry as `curated_prior` with empty `evidence_refs`, so a generated spec can never look
verified. Promotion therefore has to be a separate, explicit act on the built library, and that is
what this script does:

    python3 scripts/attach_library_evidence.py --library library/skin_xenobiotic.json \\
        --process skin_azo_dye_reduction --enzyme skin_azoreductase \\
        --refs PMID:33385118 \\
        --claim "SkinBug states that skin microbiome bacteria reduce azo dyes via azoreductase, citing Stingley 2010" \\
        --status literature_verified

Rules enforced here, because "a PMID exists" is not "the PMID supports this claim":

- `--claim` is required and is stored verbatim in `provenance_note_zh`; it must say what the
  reference actually supports, including when that is only a prediction or an extrapolation from
  another body site.
- `literature_verified` requires at least one identifier.
- identifiers must look like `PMID:12345678` or `DOI:10.xxxx/...`; anything else is rejected.
- `curated_prior` may carry identifiers too (evidence retrieved but not sufficient for the claim),
  which keeps the retrieval visible while the gate still quarantines the entry.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PMID_RE = re.compile(r"^PMID:\d{1,9}$")
DOI_RE = re.compile(r"^DOI:10\.\d{4,9}/\S+$")
STATUSES = ("curated_prior", "literature_verified")


class EntryNotFound(Exception):
    """Raised when the requested process/enzyme is not in the library file."""


def load_library(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "domain" not in data:
        raise SystemExit(f"error: {path} has no top-level 'domain'")
    return data


def find_enzyme(domain: dict[str, Any], process_id: str, enzyme_id: str) -> dict[str, Any]:
    for process in domain.get("processes") or []:
        if process.get("id") != process_id:
            continue
        for enzyme in process.get("enzymes") or []:
            if enzyme.get("id") == enzyme_id:
                return enzyme
        raise EntryNotFound(
            f"process {process_id!r} has no enzyme {enzyme_id!r}; "
            f"available: {', '.join(e.get('id','') for e in process.get('enzymes') or [])}"
        )
    raise EntryNotFound(
        f"no process {process_id!r}; available: "
        f"{', '.join(p.get('id','') for p in domain.get('processes') or [])}"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Attach retrieved references to a library entry and optionally mark it verified.",
    )
    parser.add_argument("--library", type=Path, required=True, help="library/<domain>.json to update.")
    parser.add_argument("--process", required=True, help="Process id.")
    parser.add_argument("--enzyme", required=True, help="Enzyme id within that process.")
    parser.add_argument("--refs", required=True, help="Comma-separated PMID:/DOI: identifiers.")
    parser.add_argument("--claim", required=True,
                        help="What the references actually support, in one or two sentences. Stored verbatim.")
    parser.add_argument("--status", choices=STATUSES, default="curated_prior",
                        help="curated_prior keeps the entry quarantined; literature_verified requires refs.")
    parser.add_argument("--dry-run", action="store_true", help="Show the change without writing.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.library.is_file():
        print(f"error: library not found: {args.library}", file=sys.stderr)
        return 2
    refs = [r.strip() for r in args.refs.split(",") if r.strip()]
    bad = [r for r in refs if not (PMID_RE.match(r) or DOI_RE.match(r))]
    if bad:
        print(
            f"error: not PMID:/DOI: identifiers: {', '.join(bad)}. "
            "Write PMID:12345678 or DOI:10.xxxx/yyy; a bare number or a guessed id is not acceptable.",
            file=sys.stderr,
        )
        return 2
    if args.status == "literature_verified" and not refs:
        print("error: literature_verified requires at least one identifier", file=sys.stderr)
        return 2
    if not args.claim.strip():
        print("error: --claim must say what the reference supports", file=sys.stderr)
        return 2

    data = load_library(args.library)
    try:
        enzyme = find_enzyme(data["domain"], args.process, args.enzyme)
    except EntryNotFound as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    before = {
        "evidence_status": enzyme.get("evidence_status"),
        "evidence_refs": list(enzyme.get("evidence_refs") or []),
    }
    enzyme["evidence_refs"] = refs
    enzyme["evidence_status"] = args.status
    enzyme["provenance_source"] = "literature"
    enzyme["provenance_note_zh"] = args.claim.strip()

    print(f"entry      : {args.process}/{args.enzyme}")
    print(f"before     : {before['evidence_status']} refs={before['evidence_refs']}")
    print(f"after      : {args.status} refs={refs}")
    print(f"claim      : {args.claim.strip()[:160]}")
    if args.status == "literature_verified":
        with_refs = True
    else:
        with_refs = False
    if args.dry_run:
        print("--dry-run: nothing written")
        return 0

    args.library.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.library}")
    print(
        "note: the gate needs BOTH evidence_status=literature_verified and non-empty evidence_refs."
        if with_refs
        else "note: curated_prior keeps this entry quarantined under --require-evidence, "
             "even though the references are recorded."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
