#!/usr/bin/env python3
"""Create a new starter domain for the curated target library, mechanically.

Adding body-site coverage used to mean hand-writing a large JSON file, which does
not scale and quietly invites invented EC numbers. This script turns that into a
spec -> build -> validate pipeline with the honesty rules enforced in code:

- a generated domain is **always** `content_status: starter` (it may not claim to
  be curated);
- every enzyme is **always** `evidence_status: curated_prior` with an empty
  `evidence_refs` (only `literature-evidence` may promote an entry, after it
  actually retrieved identifiers);
- every enzyme must carry a `provenance_source` and a non-empty
  `provenance_note_zh`, so the reader can see where the EC / reaction came from;
- nothing is invented: any required field left empty is a hard error, not a
  placeholder;
- the finished file is run through the real library validator before it is
  written, and is not written when validation fails.

Typical use:

    # 1. write a skeleton spec to fill in
    python3 scripts/build_library_domain.py --init --domain oral --output specs/oral.json

    # 2. build, validate, and write library/oral.json
    python3 scripts/build_library_domain.py --build --spec specs/oral.json --output library/oral.json

    # 3. confirm the whole library still validates
    python3 scripts/browse_target_library.py --validate
"""

from __future__ import annotations

import argparse
import copy
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from browse_target_library import validate_library  # noqa: E402

PROVENANCE_SOURCES = (
    "user_supplied",
    "iubmb_enzyme",
    "uniprot",
    "rhea",
    "brenda",
    "kegg",
    "ncbi",
    "literature",
    "manual_curation",
)

DOMAIN_FIELDS = (
    "id",
    "name_zh",
    "name_en",
    "keywords_zh",
    "keywords_en",
    "niche_summary_zh",
    "selection_hint_zh",
)

PROCESS_FIELDS = (
    "id",
    "name_zh",
    "name_en",
    "keywords_zh",
    "keywords_en",
    "why_it_matters_zh",
    "host_context_zh",
    "microbe_effect_zh",
    "key_taxa",
)

ENZYME_FIELDS = (
    "id",
    "enzyme_name_zh",
    "enzyme_name_en",
    "reaction_zh",
    "substrate_zh",
    "product_zh",
    "provenance_note_zh",
    "validation_note_zh",
    "provenance_source",
)

ENZYME_DEFAULTS: dict[str, Any] = {
    "gene_symbols": [],
    "ec": "",
    "ec_confidence": "none",
    "cofactor": "",
    "fold_hint": "",
    "known_microbial_examples": [],
    "entry_point": "sequence",
    "dark_matter": True,
    "priority": "medium",
    "evidence_status": "curated_prior",
    "evidence_refs": [],
}

INSTRUCTIONS = [
    "把每个空字符串换成真实内容。留空 = 构建失败，脚本不会替你编。",
    "ec 只写你确定存在的完整号；只知道家族就写 3.1.1.- 并把 ec_confidence 设为 family；"
    "确实没有 EC 号就留空并把 ec_confidence 设为 none（这是暗物质条目的正确写法）。",
    "provenance_source 必须填：iubmb_enzyme / user_supplied / uniprot / rhea / brenda / kegg / ncbi / literature / manual_curation。",
    "provenance_note_zh 写清这条目靠什么（例如“EC 号取自 IUBMB 酶命名，不是文献引用”）。",
    "validation_note_zh 必须是可证伪的实验：写清底物、读出和对照组。",
    "evidence_refs 永远留空。构建脚本会强制清空；只有 literature-evidence 真实检索后才能在库里补。",
    "生成的文件一律是 content_status=starter：它表示“覆盖可能的种子清单”，不表示已审阅完整。",
]


def skeleton(domain_id: str) -> dict[str, Any]:
    return {
        "_readme": INSTRUCTIONS,
        "library_version": "0.1.0",
        "domain": {
            "id": domain_id,
            "name_zh": "",
            "name_en": "",
            "keywords_zh": [],
            "keywords_en": [],
            "niche_summary_zh": "",
            "selection_hint_zh": "",
            "focus_taxa": [
                {
                    "taxon": "",
                    "name_zh": "",
                    "role_zh": "",
                    "attention": "medium",
                    "provenance_source": "user_supplied",
                }
            ],
            "processes": [
                {
                    "id": f"{domain_id}_process_1",
                    "name_zh": "",
                    "name_en": "",
                    "keywords_zh": [],
                    "keywords_en": [],
                    "why_it_matters_zh": "",
                    "host_context_zh": "",
                    "microbe_effect_zh": "",
                    "key_taxa": [],
                    "enzymes": [
                        {
                            "id": f"{domain_id}_enzyme_1",
                            "enzyme_name_zh": "",
                            "enzyme_name_en": "",
                            "gene_symbols": [],
                            "ec": "",
                            "ec_confidence": "none",
                            "reaction_zh": "",
                            "substrate_zh": "",
                            "product_zh": "",
                            "cofactor": "",
                            "fold_hint": "",
                            "known_microbial_examples": [],
                            "entry_point": "sequence",
                            "dark_matter": True,
                            "priority": "medium",
                            "evidence_status": "curated_prior",
                            "evidence_refs": [],
                            "provenance_note_zh": "",
                            "validation_note_zh": "",
                            "provenance_source": "iubmb_enzyme",
                        }
                    ],
                }
            ],
        },
    }


def _missing(obj: dict[str, Any], fields: tuple[str, ...], where: str) -> list[str]:
    problems: list[str] = []
    for field in fields:
        value = obj.get(field)
        if value is None:
            problems.append(f"{where}: missing '{field}'")
        elif isinstance(value, str) and not value.strip():
            problems.append(f"{where}: '{field}' is empty")
        elif isinstance(value, list) and not value and field in {"keywords_zh", "keywords_en", "key_taxa"}:
            problems.append(f"{where}: '{field}' is empty")
    return problems


def check_spec(spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    domain = spec.get("domain")
    if not isinstance(domain, dict):
        return ["spec: missing top-level 'domain' object"]
    errors.extend(_missing(domain, DOMAIN_FIELDS, "domain"))

    focus = domain.get("focus_taxa") or []
    if not focus:
        errors.append("domain.focus_taxa is empty; list at least one taxon users should consider")
    for taxon in focus:
        errors.extend(_missing(taxon, ("taxon", "name_zh", "role_zh"), f"focus_taxa/{taxon.get('taxon') or '?'}"))
        if taxon.get("provenance_source") and taxon["provenance_source"] not in PROVENANCE_SOURCES:
            errors.append(
                f"focus_taxa/{taxon.get('taxon') or '?'}: provenance_source must be one of {sorted(PROVENANCE_SOURCES)}"
            )

    processes = domain.get("processes") or []
    if not processes:
        errors.append("domain.processes is empty")
    known_taxa = {t.get("taxon") for t in focus}
    for process in processes:
        pid = process.get("id") or "?"
        where = f"processes/{pid}"
        errors.extend(_missing(process, PROCESS_FIELDS, where))
        for taxon in process.get("key_taxa") or []:
            if taxon not in known_taxa:
                errors.append(f"{where}: key_taxa '{taxon}' is not listed in domain.focus_taxa")
        enzymes = process.get("enzymes") or []
        if not enzymes:
            errors.append(f"{where}: enzymes is empty")
        for enzyme in enzymes:
            eid = enzyme.get("id") or "?"
            ewhere = f"{where}/enzymes/{eid}"
            errors.extend(_missing(enzyme, ENZYME_FIELDS, ewhere))
            source = enzyme.get("provenance_source")
            if source and source not in PROVENANCE_SOURCES:
                errors.append(f"{ewhere}: provenance_source must be one of {sorted(PROVENANCE_SOURCES)}, got {source!r}")
            confidence = enzyme.get("ec_confidence", "none")
            ec = (enzyme.get("ec") or "").strip()
            if confidence == "none" and ec:
                errors.append(f"{ewhere}: ec_confidence is 'none' but ec is {ec!r}")
            if confidence in {"full", "family"} and not ec:
                errors.append(f"{ewhere}: ec_confidence is {confidence!r} but ec is empty")
            if enzyme.get("evidence_status") not in (None, "", "curated_prior"):
                errors.append(
                    f"{ewhere}: evidence_status must stay 'curated_prior' here. "
                    "Only literature-evidence may promote an entry, after it retrieved real identifiers."
                )
            if enzyme.get("evidence_refs"):
                errors.append(
                    f"{ewhere}: remove evidence_refs from the spec. Identifiers may only be added after "
                    "literature-evidence actually retrieves them."
                )
    return errors


def build_payload(spec: dict[str, Any], spec_path: Path, version: str | None) -> dict[str, Any]:
    domain = copy.deepcopy(spec["domain"])
    # normalise taxa / enzymes and enforce the honesty invariants
    normalised_taxa = []
    for taxon in domain.get("focus_taxa") or []:
        entry = {
            "taxon": taxon["taxon"].strip(),
            "name_zh": taxon["name_zh"].strip(),
            "role_zh": taxon["role_zh"].strip(),
            "attention": taxon.get("attention") or "medium",
        }
        if taxon.get("notes_zh"):
            entry["notes_zh"] = taxon["notes_zh"]
        normalised_taxa.append(entry)

    processes = []
    for process in domain.get("processes") or []:
        enzymes = []
        for enzyme in process.get("enzymes") or []:
            entry = dict(ENZYME_DEFAULTS)
            entry.update({k: v for k, v in enzyme.items() if k not in {"_note", "_comment"}})
            entry["evidence_status"] = "curated_prior"
            entry["evidence_refs"] = []
            for key in ("gene_symbols", "known_microbial_examples", "cofactor", "fold_hint"):
                entry.setdefault(key, ENZYME_DEFAULTS.get(key))
            enzymes.append(entry)
        proc = {k: v for k, v in process.items() if k != "_note"}
        proc["enzymes"] = enzymes
        processes.append(proc)

    domain["content_status"] = "starter"
    domain["focus_taxa"] = normalised_taxa
    domain["processes"] = processes
    domain["expansion"] = {
        "method": "generated_from_spec",
        "generated_by": "scripts/build_library_domain.py",
        "spec_file": str(spec_path),
        "generated_on": _dt.date.today().isoformat(),
        "note_zh": "由 spec 机械生成，未经文献审计；evidence_refs 为空，需由 literature-evidence 复核后补。",
    }

    payload = {
        "library_version": version or spec.get("library_version") or "0.1.0",
        "reviewed_on": _dt.date.today().isoformat(),
        "domain": domain,
    }
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a starter library domain from a spec file, with honesty rules enforced.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--init", action="store_true", help="Write a skeleton spec to fill in.")
    mode.add_argument("--build", action="store_true", help="Validate the spec and write the domain file.")
    parser.add_argument("--domain", default=None, help="Domain id for --init, for example 'oral'.")
    parser.add_argument("--spec", type=Path, default=None, help="Spec file for --build.")
    parser.add_argument("--output", type=Path, required=True, help="File to write.")
    parser.add_argument("--version", default=None, help="library_version to write (default 0.1.0).")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing output file.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report, but write nothing.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.output.exists() and not args.force and not args.dry_run:
        print(f"error: {args.output} already exists; pass --force to overwrite", file=sys.stderr)
        return 2

    if args.init:
        if not args.domain:
            print("error: --init needs --domain <id>", file=sys.stderr)
            return 2
        if not args.domain.islower() or not args.domain.replace("_", "").isalnum():
            print("error: --domain must be a lowercase snake_case id", file=sys.stderr)
            return 2
        spec = skeleton(args.domain)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote skeleton spec {args.output}")
        print("下一步：逐项填写空值，然后运行")
        print(f"  python3 scripts/build_library_domain.py --build --spec {args.output} --output library/{args.domain}.json")
        return 0

    if args.spec is None:
        print("error: --build needs --spec <path>", file=sys.stderr)
        return 2
    if not args.spec.is_file():
        print(f"error: spec not found: {args.spec}", file=sys.stderr)
        return 2
    try:
        spec = json.loads(args.spec.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"error: spec is not valid JSON: {exc}", file=sys.stderr)
        return 2

    errors = check_spec(spec)
    if errors:
        print(f"spec rejected with {len(errors)} problem(s); nothing written:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    payload = build_payload(spec, args.spec, args.version)
    library_errors = validate_library([payload])
    if library_errors:
        print(f"generated domain failed library validation ({len(library_errors)} issue(s)); nothing written:", file=sys.stderr)
        for error in library_errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    domain = payload["domain"]
    n_process = len(domain["processes"])
    n_enzyme = sum(len(p["enzymes"]) for p in domain["processes"])
    summary = (
        f"domain {domain['id']} ({domain['name_zh']} / {domain['name_en']}): "
        f"{len(domain['focus_taxa'])} taxa, {n_process} processes, {n_enzyme} enzyme targets"
    )
    if args.dry_run:
        print(f"dry run OK — would write {args.output}")
        print(summary)
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    print(summary)
    print("注意：生成的域是 starter，evidence_refs 全为空。")
    print("下一步：")
    print("  python3 scripts/browse_target_library.py --validate")
    print("  然后对想用的条目跑 literature-evidence，检索到真实标识符后才能把 evidence_status 升级。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
