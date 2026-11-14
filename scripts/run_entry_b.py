#!/usr/bin/env python3
"""Entry B in one command: from a focus phrase to the recommended candidate lists.

The user should only have to say what they care about ("皮肤外源性物质代谢"). Everything after that
is a fixed route, and this script is that route:

1. search the library menu (`browse_target_library` / `resolve_target_intent`);
2. if the library covers it, seed the registries from the domain;
   if it does not, run the literature route to discover candidate enzymes and (optionally) write a
   starter domain skeleton, because "not curated yet" is not "no candidate";
3. score with `score_target_priorities --auto-score`, deriving every component the available data
   allows and recording the source of each;
4. write `recommended_enzymes.tsv` and `recommended_taxa.tsv`, which is what the user chooses from.

Nothing is asserted that the artifacts do not support: a component with no data stays empty, the
row says which component is missing, and the recommended tables only keep rows with at least two
scored components.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
RESOLVE = SCRIPT_DIR / "resolve_target_intent.py"
SCORE = SCRIPT_DIR / "score_target_priorities.py"
SHORTLIST = SCRIPT_DIR / "build_candidate_shortlist.py"
DISCOVER = SCRIPT_DIR / "discover_enzyme_candidates.py"
IMPORT_TAXA = SCRIPT_DIR / "import_taxon_list.py"

# A fixed domain-term map, not a translator: it only rewrites words that already exist in the
# plugin's own vocabulary so that an English literature query can be formed. Anything not in the map
# is left alone, and if nothing maps the script asks the user for English terms instead of guessing.
CJK_TERMS = {
    "皮肤": "skin", "肠道": "gut", "口腔": "oral", "阴道": "vaginal", "呼吸道": "respiratory",
    "菌群": "microbiome", "微生物": "microbial", "细菌": "bacteria",
    "代谢": "metabolism", "降解": "degradation", "分解": "degradation", "水解": "hydrolysis",
    "还原": "reduction", "氧化": "oxidation", "合成": "synthesis",
    "抗生素": "antibiotic", "药物": "drug", "防腐剂": "preservative", "染料": "dye",
    "偶氮": "azo", "多环芳烃": "polycyclic aromatic hydrocarbon", "香料": "fragrance",
    "外源": "xenobiotic", "外源性": "xenobiotic", "酶": "enzyme", "基因": "gene",
    "耐药": "resistance", "毒力": "virulence", "炎症": "inflammation",
}


def english_terms(topic: str) -> str:
    """Build an English query from the domain-term map; empty when nothing maps."""
    words = []
    for cjk, english in CJK_TERMS.items():
        if cjk in topic and english not in words:
            words.append(english)
    return " ".join(words)


SITE_LIST = {
    "skin": "skin_known_microbes.tsv",
    "oral": "oral_known_microbes.tsv",
}


def run(cmd: list[str], what: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"[{what}] failed:\n{(result.stderr or result.stdout)[-1200:]}", file=sys.stderr)
        raise SystemExit(2)
    return result


def route_for(topic: str) -> dict:
    result = run(
        [sys.executable, str(RESOLVE), "--query", topic, "--json"],
        "route",
    )
    return json.loads(result.stdout)


def taxa_registry(site: str, outdir: Path) -> tuple[Path | None, str]:
    name = SITE_LIST.get(site)
    if not name:
        return None, f"no taxa list bundled for site {site!r}"
    source = ROOT / "resources" / "taxa" / name
    if not source.is_file():
        return None, f"taxa list missing: {source}"
    taxa_dir = outdir / "taxa"
    target = taxa_dir / f"{site}_taxa_registry.tsv"
    if not target.is_file():
        run([sys.executable, str(IMPORT_TAXA), "--list", str(source), "--site", site,
             "--output-dir", str(taxa_dir)], "import taxa")
    return target, ""


def seed_from_library(domains: list[str], outdir: Path) -> Path | None:
    """Build an enzyme registry from the domains the router pointed at."""
    if not domains:
        return None
    seed_dir = outdir / "seed"
    seed_dir.mkdir(parents=True, exist_ok=True)
    for domain_id in domains:
        payload = json.loads((ROOT / "library" / f"{domain_id}.json").read_text(encoding="utf-8"))
        rows = ["target_id\tgene\tname\tuniprot\tec\tsite_process"]
        for process in (payload.get("domain") or {}).get("processes") or []:
            for enzyme in process.get("enzymes") or []:
                rows.append(
                    "\t".join([
                        enzyme.get("id", ""),
                        "",
                        str(enzyme.get("enzyme_name_en") or enzyme.get("enzyme_name_zh") or ""),
                        "",
                        str(enzyme.get("ec") or ""),
                        str(process.get("name_en") or process.get("name_zh") or ""),
                    ])
                )
        target = seed_dir / f"{domain_id}.enzymes.tsv"
        target.write_text("\n".join(rows) + "\n", encoding="utf-8")
    combined = seed_dir / "library.enzymes.tsv"
    merged: dict[str, str] = {}
    header = ""
    for path in sorted(seed_dir.glob("*.enzymes.tsv")):
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        if not header:
            header = lines[0]
        for line in lines[1:]:
            merged.setdefault(line.split("\t")[0], line)
    if not merged:
        return None
    combined.write_text(header + "\n" + "\n".join(merged.values()) + "\n", encoding="utf-8")
    return combined


def merge_evidence(paths: list[Path], target: Path) -> Path:
    """Concatenate evidence tables, dropping repeated (candidate_id, reference_id) pairs.

    Two discovery queries often retrieve the same paper for the same enzyme. Keeping both would
    double-count the reference, so the pair is the key.
    """
    header: list[str] = []
    rows: list[str] = []
    seen: set[tuple[str, str]] = set()
    for path in paths:
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        if not header:
            header = lines[0].split("\t")
        id_col, ref_col = header.index("candidate_id"), header.index("reference_id")
        for line in lines[1:]:
            cells = line.split("\t")
            if len(cells) <= max(id_col, ref_col):
                continue
            key = (cells[id_col], cells[ref_col])
            if key in seen:
                continue
            seen.add(key)
            rows.append(line)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(["\t".join(header)] + rows) + "\n", encoding="utf-8")
    return target


def print_table(path: Path, columns: tuple[str, ...], title: str) -> None:
    if not path.is_file():
        print(f"=== {title}：没有达到推荐门槛的条目 ===")
        return
    import csv

    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    print(f"=== {title}（{len(rows)} 条）===")
    if not rows:
        return
    widths = {c: len(c) for c in columns}
    for row in rows:
        for col in columns:
            widths[col] = max(widths[col], len(str(row.get(col, ""))[:34]))
    print("  ".join(c.ljust(widths[c]) for c in columns))
    print("  ".join("-" * widths[c] for c in columns))
    for row in rows:
        print("  ".join(str(row.get(c, ""))[:34].ljust(widths[c]) for c in columns))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Entry B end to end: focus phrase -> recommended candidate enzyme/taxa lists.",
    )
    parser.add_argument("--topic", required=True, help="What the user cares about, in their words.")
    parser.add_argument("--site", required=True, help="Body site id, e.g. skin / oral.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=20, help="Literature records per discovery query.")
    parser.add_argument("--extra-terms", action="append", default=[],
                        help="Additional discovery query; repeatable. Defaults to the topic itself.")
    parser.add_argument("--domain", action="append", default=[],
                        help="Skip routing and use these library domain ids directly.")
    parser.add_argument("--skip-discovery", action="store_true",
                        help="Do not run the literature route even when the library misses.")
    parser.add_argument("--dry-run", action="store_true", help="Show the plan, run nothing.")
    args = parser.parse_args(argv)

    outdir = args.output_dir
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"topic: {args.topic}")
    print(f"site : {args.site}")
    route = {"route": {"entry": "B", "confidence": "manual"}} if args.domain else route_for(args.topic)
    entry = route["route"].get("entry")
    hits = (route.get("library_coverage") or {}).get("hits") or []
    print(f"route: entry {entry}")
    for hit in hits[:6]:
        what = hit.get("process") or hit.get("enzyme") or ""
        print(f"  library hit: {hit.get('kind')} {hit.get('domain')} / {what}")

    domains: list[str] = list(args.domain)
    available = sorted(p.stem for p in (ROOT / "library").glob("*.json"))
    for domain_id in domains:
        if domain_id not in available:
            print(
                f"error: no library domain {domain_id!r}; available: {', '.join(available) or '—'}",
                file=sys.stderr,
            )
            return 2
    if not domains:
        for hit in hits:
            if hit.get("kind") in ("process", "enzyme") and hit.get("domain") not in domains:
                domains.append(hit.get("domain"))
    print(f"library domains in play: {domains or '—'}")

    if args.dry_run:
        print("plan: seed registries -> discover literature -> score --auto-score -> shortlist")
        return 0

    registries: list[Path] = []
    seeded = seed_from_library(domains, outdir)
    if seeded is not None:
        registries.append(seeded)
        print(f"seeded registry: {seeded}")

    evidence: Path | None = None
    need_discovery = not args.skip_discovery and (entry not in ("B",) or not seeded)
    if need_discovery:
        terms = list(dict.fromkeys(args.extra_terms))
        if not terms:
            mapped = english_terms(args.topic)
            terms = [mapped] if mapped else []
        if not terms:
            print(
                "ASK THE USER: 这个问题里没有能直接用于英文文献检索的术语。\n"
                "  给一个英文关键词，或直接给酶名 / EC，例如：\n"
                f"    python3 scripts/run_entry_b.py --topic {json.dumps(args.topic, ensure_ascii=False)} "
                f"--site {args.site} --extra-terms \"antibiotic degradation enzyme\" "
                f"--output-dir {args.output_dir}",
                file=sys.stderr,
            )
            return 2
        found: list[Path] = []
        ev_paths: list[Path] = []
        for index, term in enumerate(terms, 1):
            registry = outdir / "discovery" / f"registry_{index}.tsv"
            ev = outdir / "discovery" / f"evidence_{index}.tsv"
            result = run(
                [sys.executable, str(DISCOVER), "--site", args.site, "--terms", term,
                 "--limit", str(args.limit), "--output", str(registry), "--evidence", str(ev)],
                f"discovery: {term}", check=False,
            )
            if result.returncode != 0 or not registry.is_file():
                print(f"  discovery found nothing for {term!r} (kept going)")
                continue
            head = [line for line in result.stdout.splitlines() if line.startswith("检索")][:1]
            print(f"  discovery: {term!r} -> {head[0] if head else 'ok'}")
            found.append(registry)
            ev_paths.append(ev)
        if found:
            registries.extend(found)
            merged = merge_evidence(ev_paths, outdir / "discovery" / "literature_evidence.merged.tsv")
            evidence = merged
            print(f"literature evidence: {merged}")

    if not registries:
        print("error: no enzyme registry could be built (no library seed, no discovery hit)",
              file=sys.stderr)
        return 1

    taxa, taxa_note = taxa_registry(args.site, outdir)
    if taxa is None:
        print(f"note: {taxa_note}; taxa table will be skipped")

    cmd = [sys.executable, str(SHORTLIST), "--site", args.site]
    for domain_id in domains:
        cmd += ["--library", str(ROOT / "library" / f"{domain_id}.json")]
    for registry in registries:
        cmd += ["--enzymes", str(registry)]
    if taxa is not None:
        cmd += ["--taxa", str(taxa)]
    if evidence is not None:
        cmd += ["--literature", str(evidence)]
    cmd += ["--output-dir", str(outdir / "candidates")]
    result = run(cmd, "shortlist")
    print(result.stdout.strip())

    print()
    print_table(outdir / "candidates" / "recommended_enzymes.tsv",
                ("rank", "name", "ec", "priority_score", "scored_components", "evidence_status"),
                "推荐候选酶")
    print()
    print_table(outdir / "candidates" / "recommended_taxa.tsv",
                ("rank", "display_name", "priority_score", "scored_components",
                 "site_presence_score", "metabolic_plausibility_score"),
                "推荐候选菌")
    recommended_taxa = outdir / "candidates" / "recommended_taxa.tsv"
    if not recommended_taxa.is_file() or not recommended_taxa.read_text(encoding="utf-8").strip().split("\n")[1:]:
        print()
        full_taxa = outdir / "candidates" / "candidate_taxa.tsv"
        print("候选菌：没有菌进入推荐。")
        if full_taxa.is_file():
            print("  - 位点丰度只算 1 项，单靠它排出来的不是推荐；按丰度的完整排序在")
            print(f"    {full_taxa}")
            print("  - 要让菌进入推荐，需要其中任一项：库里的关注菌、genome-search 的基因组可得性，")
            print("    或该主题的文献证据。")
        else:
            print(f"  - 这个部位没有可用的菌名单（{taxa_note or '未提供'}），所以没有菌表可排。")
            print("  - 提供菌名单后可加入排序：python3 scripts/import_taxon_list.py --list <名单.tsv> "
                  f"--site {args.site} --output-dir {outdir / 'taxa'}")
    print()
    print(f"完整表：{outdir / 'candidates'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
