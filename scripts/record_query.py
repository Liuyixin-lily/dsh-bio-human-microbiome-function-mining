#!/usr/bin/env python3
"""Record the enzymes and processes a user asked about, without polluting the curated library.

Why a staging area instead of writing straight into `library/`:

- The library's gate is `evidence_status == literature_verified` plus non-empty `evidence_refs`.
  A query is not evidence. Putting a query into the library would undo that gate for every future
  reader.
- At the same time, asking the same question ten times should not cost ten literature searches,
  and a user's recurring interest is itself worth keeping.

So a query is recorded as `curated_prior` with empty `evidence_refs`, in
`library/_staging/queries.json`, which the library loader never reads. Promotion out of staging is
an explicit step that requires evidence references and produces a domain spec for
`build_library_domain.py --build`.

Usage:

    # record what the user asked (dedup on query+site; times_asked increments)
    python3 scripts/record_query.py --query "皮肤外源物质代谢" --site skin \\
        --process "外源物质代谢" --enzyme "esterase" --enzyme "azoreductase"

    # inspect
    python3 scripts/record_query.py --list

    # promote one entry to a domain spec, but only with evidence
    python3 scripts/record_query.py --promote q_ab12cd34 --domain skin \\
        --evidence-refs "PMID:33385118,PMID:31186074" \\
        --output specs/skin_xenobiotic.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

STAGING_VERSION = 1
DEFAULT_STAGING = Path("library/_staging/queries.json")
PMID_RE = re.compile(r"^PMID:\d{1,9}$")
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


def load_staging(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"staging_version": STAGING_VERSION, "queries": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("staging_version", STAGING_VERSION)
    data.setdefault("queries", [])
    return data


def write_staging(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def entry_id(query: str, site: str) -> str:
    digest = hashlib.sha256(f"{site}|{query}".encode("utf-8")).hexdigest()[:8]
    return f"q_{digest}"


def record(
    data: dict[str, Any],
    query: str,
    site: str,
    processes: list[str],
    enzymes: list[str],
    taxa: list[str],
    source: str,
) -> dict[str, Any]:
    wanted = entry_id(query, site)
    for item in data["queries"]:
        if item.get("id") == wanted:
            item["times_asked"] = int(item.get("times_asked") or 1) + 1
            item["last_asked"] = date.today().isoformat()
            for name in enzymes:
                if name not in item.get("enzymes", []):
                    item.setdefault("enzymes", []).append(name)
            for name in processes:
                if name not in item.get("processes", []):
                    item.setdefault("processes", []).append(name)
            for name in taxa:
                if name not in item.get("taxa", []):
                    item.setdefault("taxa", []).append(name)
            return item
    item = {
        "id": wanted,
        "query": query,
        "detected_site": site,
        "processes": processes,
        "enzymes": enzymes,
        "taxa": taxa,
        "evidence_status": "curated_prior",
        "evidence_refs": [],
        "source": source,
        "first_asked": date.today().isoformat(),
        "last_asked": date.today().isoformat(),
        "times_asked": 1,
        "promoted": False,
        "note": "用户查询记录，不是证据。要进正式库必须补 evidence_refs 并显式 promote。",
    }
    data["queries"].append(item)
    return item


def list_entries(data: dict[str, Any]) -> None:
    queries = data.get("queries") or []
    if not queries:
        print("staging 为空：还没有记录任何查询。")
        return
    print(f"{len(queries)} 条查询记录：")
    for item in sorted(queries, key=lambda q: (q.get("promoted", False), q.get("last_asked", ""))):
        flag = "已提升" if item.get("promoted") else "暂存"
        print(
            f"  [{flag}] {item['id']}  {item['query'][:44]:44} site={item['detected_site']:8} "
            f"问过 {item.get('times_asked', 1)} 次  证据 {len(item.get('evidence_refs') or [])} 条"
        )
        if item.get("enzymes"):
            print(f"            酶: {', '.join(item['enzymes'][:6])}")


def promote(
    data: dict[str, Any],
    staging_id: str,
    domain: str,
    evidence_refs: list[str],
    output: Path,
    domain_name_en: str,
) -> int:
    item = next((q for q in data["queries"] if q.get("id") == staging_id), None)
    if item is None:
        print(f"error: no staging entry {staging_id!r}; run --list", file=sys.stderr)
        return 2
    if not evidence_refs:
        print(
            "error: promotion requires evidence_refs. A query is not evidence; "
            "leave it in staging until you have retrieved references.",
            file=sys.stderr,
        )
        return 2
    bad = [ref for ref in evidence_refs if not (PMID_RE.match(ref) or DOI_RE.match(ref))]
    if bad:
        print(f"error: not PMID:/DOI: identifiers: {', '.join(bad)}", file=sys.stderr)
        return 2
    enzymes = item.get("enzymes") or []
    processes = item.get("processes") or [item["query"]]
    if not enzymes:
        print(
            "error: this staging entry names no enzyme, so it cannot become a library enzyme target. "
            "Record the enzyme names first (--enzyme).",
            file=sys.stderr,
        )
        return 2
    spec = {
        "id": domain,
        "name_zh": item["detected_site"],
        "name_en": domain_name_en,
        "keywords_zh": [],
        "keywords_en": [],
        "niche_summary_zh": f"由用户查询「{item['query']}」提升而来。",
        "selection_hint_zh": (
            "条目只含用户问到的酶与过程；证据尚未逐条核对，构建前请确认每个酶都有对应引用。"
        ),
        "focus_taxa": [{"taxon": taxon, "attention": "medium"} for taxon in item.get("taxa") or []],
        "processes": [
            {
                "id": "promoted_process_1",
                "name_zh": processes[0],
                "keywords_zh": [],
                "keywords_en": [],
                "why_it_matters_zh": f"用户关注：{item['query']}",
                "enzymes": [
                    {
                        "id": re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or f"enzyme_{i}",
                        "enzyme_name_zh": name,
                        "enzyme_name_en": name,
                        "ec": "",
                        "ec_confidence": "none",
                        "entry_point": "manual",
                        "dark_matter": False,
                        "priority": "medium",
                        "evidence_status": "curated_prior",
                        # build_library_domain rejects refs inside a starter spec; the retrieved
                        # identifiers go to a sidecar and stay attributed here in prose
                        "evidence_refs": [],
                        "provenance_source": "user_query",
                        "provenance_note_zh": (
                            f"来自用户查询记录 {staging_id}：{item['query']}。"
                            f"已检索到的文献（待逐条核对后写入 evidence_refs）：{', '.join(evidence_refs)}"
                        ),
                    }
                    for i, name in enumerate(enzymes, 1)
                ],
            }
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"domain": spec}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sidecar = output.with_suffix(".evidence.json")
    sidecar.write_text(
        json.dumps(
            {
                "staging_id": staging_id,
                "query": item["query"],
                "evidence_refs": evidence_refs,
                "attribution": (
                    "Retrieved by the literature route and recorded here because a starter spec may not "
                    "carry evidence_refs. Check each reference against the specific enzyme claim, then "
                    "attach it in the curated JSON and set evidence_status=literature_verified."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote evidence sidecar {sidecar} (spec itself keeps evidence_refs empty)")
    item["promoted"] = True
    item["evidence_refs"] = evidence_refs
    item["evidence_status"] = "curated_prior"
    print(f"wrote domain spec {output}")
    print(
        "下一步：补全 spec 里空的 EC / 关键词 / 证据归属，然后\n"
        f"  python3 scripts/build_library_domain.py --build --spec {output} --output library/{domain}.json"
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record user queries into a staging area; promote to a domain spec only with evidence.",
    )
    parser.add_argument("--query", help="The user's own words.")
    parser.add_argument("--site", default="", help="Body site id, e.g. skin / gut / oral.")
    parser.add_argument("--process", action="append", default=[], help="Process name mentioned; repeatable.")
    parser.add_argument("--enzyme", action="append", default=[], help="Enzyme name mentioned; repeatable.")
    parser.add_argument("--taxon", action="append", default=[], help="Taxon mentioned; repeatable.")
    parser.add_argument("--source", default="cli", help="Where the query came from (cli / agent / import).")
    parser.add_argument("--staging", type=Path, default=DEFAULT_STAGING, help="Staging JSON path.")
    parser.add_argument("--list", action="store_true", help="Show recorded queries.")
    parser.add_argument("--promote", metavar="ID", help="Promote a staging entry to a domain spec.")
    parser.add_argument("--domain", default="", help="Domain id for --promote.")
    parser.add_argument("--domain-name-en", default="", help="English domain name for --promote.")
    parser.add_argument("--evidence-refs", default="", help="Comma-separated PMID:/DOI: refs; required to promote.")
    parser.add_argument("--output", type=Path, help="Domain spec path for --promote.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    data = load_staging(args.staging)

    if args.list:
        list_entries(data)
        return 0

    if args.promote:
        refs = [r.strip() for r in args.evidence_refs.split(",") if r.strip()]
        if args.output is None:
            print("error: --promote needs --output", file=sys.stderr)
            return 2
        rc = promote(data, args.promote, args.domain or "promoted", refs, args.output,
                     args.domain_name_en or args.domain or "Promoted domain")
        if rc == 0:
            write_staging(args.staging, data)
        return rc

    if not args.query:
        print("error: pass --query (or --list / --promote)", file=sys.stderr)
        return 2
    if not args.site:
        print(
            "error: --site is required. The site is part of the identity: the same wording about "
            "'代谢' means something different on skin and in the gut.",
            file=sys.stderr,
        )
        return 2

    item = record(data, args.query, args.site, args.process, args.enzyme, args.taxon, args.source)
    write_staging(args.staging, data)
    print(
        f"recorded {item['id']} (问过 {item['times_asked']} 次) -> {args.staging}\n"
        "状态：curated_prior，evidence_refs 为空。这是查询记录，不是证据；正式库不会读到它。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
