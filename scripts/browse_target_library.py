#!/usr/bin/env python3
"""Browse, search, and select targets from the curated target library.

The target library turns a vague natural-language interest ("油脂分泌", "体味",
"which skin enzymes are worth screening?") into a concrete screening target with a
recommended workflow entry point. It is a curated prior, not proof: every enzyme
entry carries `evidence_status` and an empty `evidence_refs` list until
`literature-evidence` actually retrieves identifiers.

Hierarchy: domain (body site) -> process (physiological process) -> enzyme target.

Typical use:

    # what body sites are available?
    python3 scripts/browse_target_library.py --list-domains

    # what processes exist for skin, in plain words?
    python3 scripts/browse_target_library.py --list-processes skin

    # natural-language keyword search across the whole library
    python3 scripts/browse_target_library.py --search "油脂分泌"

    # expand one process and show the enzyme targets
    python3 scripts/browse_target_library.py --show skin_sebum_lipolysis

    # menu-driven selection, ending in a target_function_card.json
    python3 scripts/browse_target_library.py --interactive --output-dir outputs/task

    # hand the whole library to Excel
    python3 scripts/browse_target_library.py --export-tsv outputs/task/target_library.tsv

    # audit the library content itself
    python3 scripts/browse_target_library.py --validate
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_LIBRARY_DIR = SCRIPT_DIR.parent / "library"

EC_PATTERN = re.compile(r"^[1-7]\.\d{1,2}\.\d{1,2}\.(?:\d{1,3}|-)$")
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
REF_PATTERN = re.compile(r"^(?:PMID:\d{1,9}|DOI:10\.\d{4,9}/\S+)$")

ENUM_EC_CONFIDENCE = {"full", "family", "none"}
ENUM_ENTRY_POINT = {"reaction", "ec", "sequence"}
ENUM_PRIORITY = {"high", "medium", "low"}
ENUM_EVIDENCE = {"curated_prior", "literature_verified"}
ENUM_ATTENTION = {"high", "medium", "low"}
ENUM_CONTENT_STATUS = {"curated", "starter"}
ENUM_DOMAIN_ROLE = {"shipped_example", "user_defined"}
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

DOMAIN_REQUIRED = (
    "id",
    "name_zh",
    "name_en",
    "content_status",
    "keywords_zh",
    "keywords_en",
    "niche_summary_zh",
    "selection_hint_zh",
    "focus_taxa",
    "processes",
)
TAXON_REQUIRED = ("taxon", "name_zh", "role_zh", "attention")
PROCESS_REQUIRED = (
    "id",
    "name_zh",
    "name_en",
    "keywords_zh",
    "keywords_en",
    "why_it_matters_zh",
    "host_context_zh",
    "microbe_effect_zh",
    "key_taxa",
    "enzymes",
)
ENZYME_REQUIRED = (
    "id",
    "enzyme_name_zh",
    "enzyme_name_en",
    "gene_symbols",
    "ec",
    "ec_confidence",
    "reaction_zh",
    "substrate_zh",
    "product_zh",
    "cofactor",
    "fold_hint",
    "known_microbial_examples",
    "entry_point",
    "dark_matter",
    "priority",
    "evidence_status",
    "evidence_refs",
    "provenance_note_zh",
    "validation_note_zh",
)

TSV_FIELDS = [
    "domain_id",
    "domain_name_zh",
    "process_id",
    "process_name_zh",
    "process_name_en",
    "process_keywords_zh",
    "enzyme_id",
    "enzyme_name_zh",
    "enzyme_name_en",
    "gene_symbols",
    "ec",
    "ec_confidence",
    "reaction_zh",
    "substrate_zh",
    "product_zh",
    "cofactor",
    "fold_hint",
    "known_microbial_taxa",
    "entry_point",
    "dark_matter",
    "priority",
    "evidence_status",
    "evidence_refs",
    "validation_note_zh",
]


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------


def library_files(library_dir: Path) -> list[Path]:
    if not library_dir.is_dir():
        return []
    files = sorted(p for p in library_dir.glob("*.json") if p.is_file())
    # schema/example files that live next to the data should not be treated as data
    return [p for p in files if not p.name.endswith(".schema.json")]


def load_library(library_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (domain_payloads, load_errors)."""
    payloads: list[dict[str, Any]] = []
    errors: list[str] = []
    files = library_files(library_dir)
    if not files:
        errors.append(f"no library JSON files found in {library_dir}")
        return payloads, errors
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path.name}: not valid JSON ({exc})")
            continue
        if not isinstance(data, dict) or "domain" not in data:
            errors.append(f"{path.name}: missing top-level 'domain' object")
            continue
        data["_source_file"] = path.name
        payloads.append(data)
    return payloads, errors


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------


def _require(obj: dict[str, Any], keys: tuple[str, ...], where: str, errors: list[str]) -> None:
    for key in keys:
        if key not in obj:
            errors.append(f"{where}: missing required field '{key}'")


def _check_enum(
    value: Any, allowed: set[str], where: str, field: str, errors: list[str]
) -> None:
    if value not in allowed:
        errors.append(
            f"{where}: {field} must be one of {sorted(allowed)}, got {value!r}"
        )


def validate_library(payloads: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen_domains: dict[str, str] = {}
    seen_processes: dict[str, str] = {}
    seen_enzymes: dict[str, str] = {}

    for payload in payloads:
        source = payload.get("_source_file", "?")
        version = payload.get("library_version")
        if not isinstance(version, str) or not SEMVER_PATTERN.match(version):
            errors.append(f"{source}: library_version must look like 1.0.0, got {version!r}")
        reviewed = payload.get("reviewed_on")
        if reviewed is not None and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(reviewed)):
            errors.append(f"{source}: reviewed_on must be YYYY-MM-DD, got {reviewed!r}")

        domain = payload.get("domain")
        if not isinstance(domain, dict):
            errors.append(f"{source}: 'domain' must be an object")
            continue
        _require(domain, DOMAIN_REQUIRED, source, errors)
        domain_id = domain.get("id", "")
        if not ID_PATTERN.match(str(domain_id)):
            errors.append(f"{source}: domain.id {domain_id!r} must be snake_case")
        if domain_id in seen_domains:
            errors.append(f"{source}: duplicate domain.id {domain_id!r} (also in {seen_domains[domain_id]})")
        seen_domains[str(domain_id)] = source
        _check_enum(
            domain.get("content_status"),
            ENUM_CONTENT_STATUS,
            source,
            "domain.content_status",
            errors,
        )

        if domain.get("role") is not None:
            _check_enum(domain.get("role"), ENUM_DOMAIN_ROLE, source, "domain.role", errors)

        expansion = domain.get("expansion")
        generated = isinstance(expansion, dict) and expansion.get("method") == "generated_from_spec"
        if expansion is not None:
            if not isinstance(expansion, dict):
                errors.append(f"{source}: domain.expansion must be an object")
                generated = False
            else:
                _check_enum(
                    expansion.get("method"),
                    {"manual_curation", "generated_from_spec"},
                    source,
                    "domain.expansion.method",
                    errors,
                )
                if generated and domain.get("role") == "shipped_example":
                    errors.append(
                        f"{source}: a domain generated from a spec must be role='user_defined'; "
                        "only the domains shipped with the plugin are reference examples"
                    )
                if generated and domain.get("content_status") != "starter":
                    errors.append(
                        f"{source}: a domain generated from a spec must stay content_status='starter'; "
                        "generated content may not claim to be curated"
                    )

        taxa: set[str] = set()
        focus_taxa = domain.get("focus_taxa") or []
        if not focus_taxa:
            errors.append(f"{source}: domain.focus_taxa is empty; list the taxa users should consider")
        for taxon in focus_taxa:
            if not isinstance(taxon, dict):
                errors.append(f"{source}: each focus_taxa entry must be an object")
                continue
            _require(taxon, TAXON_REQUIRED, f"{source}/focus_taxa", errors)
            name = str(taxon.get("taxon", ""))
            if name:
                taxa.add(name)
            _check_enum(
                taxon.get("attention"),
                ENUM_ATTENTION,
                f"{source}/focus_taxa/{name or '?'}",
                "attention",
                errors,
            )

        processes = domain.get("processes") or []
        if not processes:
            errors.append(f"{source}: domain.processes is empty")
        for process in processes:
            if not isinstance(process, dict):
                errors.append(f"{source}: each process must be an object")
                continue
            pid = str(process.get("id", ""))
            where = f"{source}/processes/{pid or '?'}"
            _require(process, PROCESS_REQUIRED, where, errors)
            if not ID_PATTERN.match(pid):
                errors.append(f"{where}: process.id must be snake_case")
            if pid in seen_processes:
                errors.append(f"{where}: duplicate process.id (also in {seen_processes[pid]})")
            seen_processes[pid] = source

            for keyword_field in ("keywords_zh", "keywords_en"):
                keywords = process.get(keyword_field)
                if not isinstance(keywords, list) or not keywords:
                    errors.append(f"{where}: {keyword_field} must be a non-empty list")
            key_taxa = process.get("key_taxa") or []
            if not key_taxa:
                errors.append(f"{where}: key_taxa is empty")
            for name in key_taxa:
                if name not in taxa:
                    errors.append(
                        f"{where}: key_taxa {name!r} is not listed in domain.focus_taxa"
                    )

            enzymes = process.get("enzymes") or []
            if not enzymes:
                errors.append(f"{where}: enzymes is empty; a process with no target is not selectable")
            for enzyme in enzymes:
                if not isinstance(enzyme, dict):
                    errors.append(f"{where}: each enzyme must be an object")
                    continue
                errors.extend(validate_enzyme(enzyme, where, seen_enzymes, generated=generated))

    return errors


def validate_enzyme(
    enzyme: dict[str, Any],
    where: str,
    seen_enzymes: dict[str, str],
    generated: bool = False,
) -> list[str]:
    errors: list[str] = []
    eid = str(enzyme.get("id", ""))
    here = f"{where}/enzymes/{eid or '?'}"
    _require(enzyme, ENZYME_REQUIRED, here, errors)
    if not ID_PATTERN.match(eid):
        errors.append(f"{here}: enzyme.id must be snake_case")
    if eid in seen_enzymes:
        errors.append(f"{here}: duplicate enzyme.id (also in {seen_enzymes[eid]})")
    seen_enzymes[eid] = where

    ec = str(enzyme.get("ec", ""))
    confidence = enzyme.get("ec_confidence")
    _check_enum(confidence, ENUM_EC_CONFIDENCE, here, "ec_confidence", errors)
    if confidence == "none" and ec:
        errors.append(
            f"{here}: ec_confidence is 'none' but ec is {ec!r}; either give the EC and raise confidence, "
            "or leave ec empty so the dark-matter status is visible"
        )
    if confidence in {"full", "family"} and not EC_PATTERN.match(ec):
        errors.append(f"{here}: ec {ec!r} is not a valid EC number or family-level value")
    if confidence == "full" and ec.endswith("-"):
        errors.append(f"{here}: ec_confidence is 'full' but ec {ec!r} is family-level")

    _check_enum(enzyme.get("entry_point"), ENUM_ENTRY_POINT, here, "entry_point", errors)
    _check_enum(enzyme.get("priority"), ENUM_PRIORITY, here, "priority", errors)
    _check_enum(enzyme.get("evidence_status"), ENUM_EVIDENCE, here, "evidence_status", errors)
    if not isinstance(enzyme.get("dark_matter"), bool):
        errors.append(f"{here}: dark_matter must be true or false")

    refs = enzyme.get("evidence_refs")
    if not isinstance(refs, list):
        errors.append(f"{here}: evidence_refs must be a list")
        refs = []
    for ref in refs:
        if not REF_PATTERN.match(str(ref)):
            errors.append(
                f"{here}: evidence_ref {ref!r} is not a verifiable PMID/DOI identifier"
            )
    if enzyme.get("evidence_status") == "literature_verified" and not refs:
        errors.append(
            f"{here}: evidence_status is literature_verified but evidence_refs is empty; "
            "downgrade to curated_prior until literature-evidence returns identifiers"
        )

    provenance_source = enzyme.get("provenance_source")
    if provenance_source is not None:
        _check_enum(
            provenance_source,
            set(PROVENANCE_SOURCES),
            here,
            "provenance_source",
            errors,
        )
    elif generated:
        errors.append(
            f"{here}: generated domains must record provenance_source for every enzyme "
            f"(one of {sorted(PROVENANCE_SOURCES)})"
        )

    examples = enzyme.get("known_microbial_examples")
    if not isinstance(examples, list):
        errors.append(f"{here}: known_microbial_examples must be a list")
    elif enzyme.get("priority") == "high" and not examples:
        errors.append(
            f"{here}: priority is high but known_microbial_examples is empty; "
            "a high-priority target needs at least one named representative"
        )
    return errors


# --------------------------------------------------------------------------
# indexing / search
# --------------------------------------------------------------------------


class Index:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.domains: list[dict[str, Any]] = []
        # taxon name -> list of {domain, role_zh, attention, processes}
        self.taxa: dict[str, list[dict[str, Any]]] = {}
        self.payload_of: dict[str, dict[str, Any]] = {}
        for payload in payloads:
            domain = payload["domain"]
            domain["_library_version"] = payload.get("library_version", "")
            domain["_reviewed_on"] = payload.get("reviewed_on", "")
            domain["_source_file"] = payload.get("_source_file", "")
            self.domains.append(domain)
            self.payload_of[domain["id"]] = payload
        self.domains.sort(key=lambda d: d["id"])
        for domain in self.domains:
            process_of: dict[str, list[str]] = {}
            for process in domain.get("processes") or []:
                for name in process.get("key_taxa") or []:
                    process_of.setdefault(name, []).append(process["id"])
            for taxon in domain.get("focus_taxa") or []:
                name = taxon.get("taxon", "")
                if not name:
                    continue
                self.taxa.setdefault(name, []).append(
                    {
                        "domain": domain["id"],
                        "name_zh": taxon.get("name_zh", ""),
                        "role_zh": taxon.get("role_zh", ""),
                        "attention": taxon.get("attention", ""),
                        "processes": process_of.get(name, []),
                    }
                )

    def domain(self, domain_id: str) -> dict[str, Any] | None:
        for domain in self.domains:
            if domain["id"] == domain_id:
                return domain
        return None

    def iter_processes(self, domain: dict[str, Any]):
        for process in domain.get("processes", []):
            yield process

    def iter_enzymes(self, domain: dict[str, Any], process: dict[str, Any]):
        seen: set[str] = set()
        for enzyme in process.get("enzymes", []):
            if enzyme["id"] in seen:
                continue
            seen.add(enzyme["id"])
            yield enzyme

    def find_process(self, process_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        for domain in self.domains:
            for process in self.iter_processes(domain):
                if process["id"] == process_id:
                    return domain, process
        return None

    def find_enzyme(self, enzyme_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
        for domain in self.domains:
            for process in self.iter_processes(domain):
                for enzyme in self.iter_enzymes(domain, process):
                    if enzyme["id"] == enzyme_id:
                        return domain, process, enzyme
        return None

    def resolve(self, key: str) -> dict[str, Any] | None:
        """Resolve a domain id, process id, enzyme id, or a bare number-free alias."""
        key = key.strip()
        if not key:
            return None
        domain = self.domain(key)
        if domain is not None:
            return {"kind": "domain", "domain": domain}
        hit = self.find_process(key)
        if hit is not None:
            return {"kind": "process", "domain": hit[0], "process": hit[1]}
        hit = self.find_enzyme(key)
        if hit is not None:
            return {"kind": "enzyme", "domain": hit[0], "process": hit[1], "enzyme": hit[2]}
        return None


def _strings_of_enzyme(enzyme: dict[str, Any]) -> list[str]:
    out = [
        enzyme.get("enzyme_name_zh", ""),
        enzyme.get("enzyme_name_en", ""),
        enzyme.get("id", ""),
        enzyme.get("reaction_zh", ""),
        enzyme.get("substrate_zh", ""),
        enzyme.get("product_zh", ""),
        enzyme.get("ec", ""),
        enzyme.get("fold_hint", ""),
    ]
    out.extend(enzyme.get("gene_symbols") or [])
    for example in enzyme.get("known_microbial_examples") or []:
        out.append(example.get("taxon", ""))
        out.append(example.get("detail_zh", ""))
    return [s for s in out if s]


def _strings_of_process(process: dict[str, Any]) -> list[str]:
    out = [
        process.get("name_zh", ""),
        process.get("name_en", ""),
        process.get("id", ""),
        process.get("why_it_matters_zh", ""),
        process.get("host_context_zh", ""),
        process.get("microbe_effect_zh", ""),
    ]
    out.extend(process.get("keywords_zh") or [])
    out.extend(process.get("keywords_en") or [])
    out.extend(process.get("key_taxa") or [])
    return [s for s in out if s]


def _strings_of_domain(domain: dict[str, Any]) -> list[str]:
    out = [
        domain.get("name_zh", ""),
        domain.get("name_en", ""),
        domain.get("id", ""),
        domain.get("niche_summary_zh", ""),
    ]
    out.extend(domain.get("keywords_zh") or [])
    out.extend(domain.get("keywords_en") or [])
    return [s for s in out if s]


def _reverse_containment_ok(field: str) -> bool:
    """Guard reverse containment against very short keywords.

    Short curated keywords such as "NO" or "pH" are legitimate entries, but they
    appear inside unrelated words all the time, so they must only score on an
    exact match, never as a substring of the user's sentence. CJK keywords carry
    much more information per character, so two characters are enough there.
    """
    if any(ord(char) > 127 for char in field):
        return len(field) >= 2
    return len(field) >= 3


def _score_tokens(tokens: list[str], needle_fields: list[str], haystack: list[str]) -> int:
    """Score one object against all query tokens.

    Scoring per token:
      100 = the token is exactly a curated keyword
       80 = a curated keyword appears inside the token (see note below)
       60 = the token appears inside a curated keyword
       20 = the token appears somewhere in the free-text fields

    A token must reach at least 20 to count as covered, so multi-word queries
    behave like AND instead of matching any stray word.

    The 80-level reverse containment matters in practice: users type whole
    sentences ("我关注油脂分泌", "皮肤代谢有哪些重要的生理过程"), so the library
    keyword is usually a substring of the query, not the other way round.
    """
    total = 0
    lowered_haystack = [h.lower() for h in haystack]
    for token in tokens:
        best = 0
        for field in needle_fields:
            field = field.lower()
            if not field:
                continue
            if token == field:
                best = max(best, 100)
            elif _reverse_containment_ok(field) and field in token:
                best = max(best, 80)
            elif token in field:
                best = max(best, 60)
        for text in lowered_haystack:
            if token in text:
                best = max(best, 20 if best < 60 else best)
        if best < 20:
            return 0
        total += best
    return total


def search(index: Index, query: str) -> list[dict[str, Any]]:
    tokens = [t.lower() for t in query.split() if t.strip()]
    if not tokens:
        return []
    hits: list[dict[str, Any]] = []
    for domain in index.domains:
        domain_keywords = [k.lower() for k in (domain.get("keywords_zh") or []) + (domain.get("keywords_en") or [])]
        domain_score = _score_tokens(tokens, domain_keywords, _strings_of_domain(domain))
        if domain_score:
            hits.append({"kind": "domain", "score": domain_score, "domain": domain})
        for process in index.iter_processes(domain):
            process_keywords = [
                k.lower() for k in (process.get("keywords_zh") or []) + (process.get("keywords_en") or [])
            ]
            process_score = _score_tokens(tokens, process_keywords, _strings_of_process(process))
            if process_score:
                hits.append(
                    {
                        "kind": "process",
                        "score": process_score + 10,  # a process is usually the better answer than the site
                        "domain": domain,
                        "process": process,
                    }
                )
            for enzyme in index.iter_enzymes(domain, process):
                enzyme_keywords = [
                    k.lower()
                    for k in (enzyme.get("enzyme_name_zh"), enzyme.get("enzyme_name_en"), enzyme.get("ec"))
                    + tuple(enzyme.get("gene_symbols") or [])
                    if k
                ]
                enzyme_score = _score_tokens(tokens, enzyme_keywords, _strings_of_enzyme(enzyme))
                if enzyme_score:
                    hits.append(
                        {
                            "kind": "enzyme",
                            "score": enzyme_score,
                            "domain": domain,
                            "process": process,
                            "enzyme": enzyme,
                        }
                    )
    for name, records in index.taxa.items():
        lowered = name.lower()
        score = 0
        for token in tokens:
            if token == lowered:
                score += 100
            elif len(lowered) >= 4 and lowered in token:
                score += 80
            elif len(token) >= 4 and token in lowered:
                score += 60
        if score and all(_token_hits_taxon(t, name) for t in tokens):
            hits.append({"kind": "taxon", "score": score + 5, "taxon": name, "records": records})

    hits.sort(key=lambda h: (-h["score"], h["kind"] != "process", h.get("process", {}).get("id", "")))
    return hits


def _token_hits_taxon(token: str, taxon: str) -> bool:
    lowered = taxon.lower()
    return token == lowered or (len(lowered) >= 4 and lowered in token) or (len(token) >= 4 and token in lowered)


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def _merged_taxa_view(index: "Index", domains: list[dict[str, Any]]) -> dict[str, Any]:
    """Synthesise one taxon list across domains, so 'all' keeps the same code path."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for domain in domains:
        for taxon in domain.get("focus_taxa") or []:
            key = taxon.get("taxon", "")
            if key in seen:
                continue
            seen.add(key)
            merged.append({**taxon, "_domain": domain["id"]})
    return {
        "id": "all",
        "name_zh": "全部部位",
        "name_en": "All domains",
        "attention_order_hint": True,
        "focus_taxa": merged,
        "processes": [p for d in domains for p in d.get("processes") or []],
    }


def fmt_keywords(items: list[str], limit: int = 8) -> str:
    return ", ".join(items[:limit]) + (" …" if len(items) > limit else "")


def render_domain_line(domain: dict[str, Any]) -> str:
    n_process = len(domain.get("processes") or [])
    n_enzyme = sum(len(p.get("enzymes") or []) for p in domain.get("processes") or [])
    role = domain.get("role")
    role_tag = "" if role in (None, "shipped_example") else f" [{role}]"
    return (
        f"{domain['id']:<8} {domain['name_zh']} / {domain['name_en']} "
        f"[{domain.get('content_status')}]{role_tag}  {n_process} processes, {n_enzyme} enzyme targets"
    )


def render_process_block(domain: dict[str, Any], process: dict[str, Any], verbose: bool = True) -> str:
    lines = [f"{process['id']}  {process['name_zh']} / {process['name_en']}"]
    if verbose:
        lines.append(f"  keywords : {fmt_keywords((process.get('keywords_zh') or []) + (process.get('keywords_en') or []))}")
        lines.append(f"  why      : {process.get('why_it_matters_zh', '')}")
        lines.append(f"  taxa     : {', '.join(process.get('key_taxa') or [])}")
    else:
        lines.append(f"  {process.get('why_it_matters_zh', '')}")
    lines.append("  enzymes  :")
    for enzyme in process.get("enzymes") or []:
        ec = enzyme.get("ec") or "no EC"
        flags = []
        if enzyme.get("dark_matter"):
            flags.append("dark-matter")
        flags.append(f"priority={enzyme.get('priority')}")
        flag_text = " ".join(flags)
        lines.append(
            f"    - {enzyme['id']:<38} {enzyme.get('enzyme_name_zh')} / {enzyme.get('enzyme_name_en')}"
        )
        lines.append(
            f"      EC {ec} ({enzyme.get('ec_confidence')})  entry_point={enzyme.get('entry_point')}  {flag_text}"
        )
        if verbose:
            lines.append(f"      reaction: {enzyme.get('reaction_zh')}")
            lines.append(f"      validate: {enzyme.get('validation_note_zh')}")
    return "\n".join(lines)


META_TOKENS_ZH = (
    "哪些", "什么", "有什么", "都有", "关注", "值得", "重要", "介绍", "列出",
    "看看", "多少", "清单", "列表",
)
META_TOKENS_EN = (
    "which", "what", "list", "show", "available", "options", "important", "worth",
)


def looks_like_navigation(query: str) -> bool:
    """True when the user is asking what the library contains, not naming a topic.

    "都有哪些关注的菌" / "which enzymes are worth looking at" carry no domain or
    process word, so keyword search must not pretend to be a miss. The right
    answer is to show the library's own menu.
    """
    lowered = query.lower()
    if any(token in lowered for token in META_TOKENS_ZH):
        return True
    return any(token in lowered for token in META_TOKENS_EN)


def render_navigation(index: "Index", query: str) -> str:
    wants_taxa = "菌" in query or "taxa" in query.lower() or "microbe" in query.lower()
    wants_process = any(t in query for t in ("过程", "代谢", "酶")) or "process" in query.lower()
    lines = [f"「{query}」看起来是在问库里有什么，而不是在指某个具体主题。"]
    lines.append("这个库分三层，可以任意一层进入：")
    lines.append("")
    for domain in index.domains:
        n_process = len(domain.get("processes") or [])
        n_enzyme = sum(len(p.get("enzymes") or []) for p in domain.get("processes") or [])
        n_taxon = len(domain.get("focus_taxa") or [])
        lines.append(
            f"  {domain['id']:<6} {domain['name_zh']} / {domain['name_en']} "
            f"[{domain.get('content_status')}]  {n_process} 个生理过程 · {n_enzyme} 个酶目标 · {n_taxon} 个关注菌"
        )
    lines.append("")
    domain_ids = " / ".join(d["id"] for d in index.domains)
    if wants_taxa:
        lines.append(f"  看关注菌      python3 scripts/browse_target_library.py --list-taxa <{domain_ids}>")
    if wants_process:
        lines.append(f"  看生理过程    python3 scripts/browse_target_library.py --list-processes <{domain_ids}>")
    if not (wants_taxa or wants_process):
        lines.append(f"  看生理过程    python3 scripts/browse_target_library.py --list-processes <{domain_ids}>")
        lines.append(f"  看关注菌      python3 scripts/browse_target_library.py --list-taxa <{domain_ids}>")
    lines.append("  菜单式选择    python3 scripts/browse_target_library.py --interactive --output-dir <project_dir>")
    lines.append("")
    lines.append("或者直接说你关注的具体表型（油脂分泌 / 体味 / 头皮屑 …），我用关键词定位。")
    return "\n".join(lines)


def render_hit(hit: dict[str, Any]) -> str:
    if hit["kind"] == "taxon":
        lines = []
        for record in hit["records"]:
            procs = ", ".join(record["processes"]) or "(no process yet)"
            first = record["processes"][0] if record["processes"] else record["domain"]
            lines.append(
                f"[{hit['score']:>3}] TAXON   {hit['taxon']}  {record['name_zh']} "
                f"[关注度={record['attention']}] @ {record['domain']}\n"
                f"        {record['role_zh']}\n"
                f"        -> --show {first}   processes: {procs}"
            )
        return "\n".join(lines)
    domain = hit["domain"]
    if hit["kind"] == "domain":
        n_process = len(domain.get("processes") or [])
        n_enzyme = sum(len(p.get("enzymes") or []) for p in domain.get("processes") or [])
        return (
            f"[{hit['score']:>3}] DOMAIN  {domain['id']}: {domain['name_zh']} / {domain['name_en']} "
            f"({n_process} processes, {n_enzyme} enzyme targets)\n"
            f"        -> 看生理过程: --list-processes {domain['id']}"
            f"   看关注菌: --list-taxa {domain['id']}"
        )
    process = hit["process"]
    if hit["kind"] == "process":
        return (
            f"[{hit['score']:>3}] PROCESS {domain['id']} / {process['id']}: "
            f"{process['name_zh']} / {process['name_en']}"
        )
    if hit["kind"] == "taxon":
        lines = []
        for record in hit["records"]:
            procs = ", ".join(record["processes"]) or "(no process yet)"
            lines.append(
                f"[{hit['score']:>3}] TAXON   {hit['taxon']}  {record['name_zh']} "
                f"[关注度={record['attention']}] @ {record['domain']}\n"
                f"        {record['role_zh']}\n"
                f"        -> --show {record['processes'][0] if record['processes'] else record['domain']}"
                f"   processes: {procs}"
            )
        return "\n".join(lines)
    enzyme = hit["enzyme"]
    ec = enzyme.get("ec") or "no EC"
    return (
        f"[{hit['score']:>3}] ENZYME  {domain['id']} / {process['id']} / {enzyme['id']}: "
        f"{enzyme['enzyme_name_zh']} / {enzyme['enzyme_name_en']} (EC {ec})"
    )


# --------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------


def build_card_from_enzyme(
    domain: dict[str, Any],
    process: dict[str, Any],
    enzyme: dict[str, Any],
    target_id: str | None = None,
) -> dict[str, Any]:
    sys.path.insert(0, str(SCRIPT_DIR))
    from build_target_function_card import build_card  # noqa: PLC0415

    taxa = [ex.get("taxon", "") for ex in enzyme.get("known_microbial_examples") or []]
    notes_lines = [
        f"library_domain: {domain['id']} ({domain['name_zh']})",
        f"library_process: {process['id']} ({process['name_zh']})",
        f"library_enzyme: {enzyme['id']}",
        f"recommended_entry_point: {enzyme['entry_point']}",
        f"dark_matter: {'yes' if enzyme.get('dark_matter') else 'no'}",
        f"priority: {enzyme.get('priority')}",
        f"process_key_taxa: {', '.join(process.get('key_taxa') or [])}",
        f"evidence_status: {enzyme.get('evidence_status')} (evidence_refs must stay empty until literature-evidence retrieves identifiers)",
        f"provenance: {enzyme.get('provenance_note_zh', '')}",
        f"validation: {enzyme.get('validation_note_zh', '')}",
        f"why_it_matters: {process.get('why_it_matters_zh', '')}",
    ]
    return build_card(
        target_id=target_id or enzyme["id"],
        enzyme_name=enzyme["enzyme_name_en"],
        ec=enzyme.get("ec", ""),
        reaction=enzyme.get("reaction_zh", ""),
        substrate=enzyme.get("substrate_zh", ""),
        product=enzyme.get("product_zh", ""),
        cofactor=enzyme.get("cofactor", ""),
        structural_fold=enzyme.get("fold_hint", ""),
        pathway=f"{domain.get('name_en')} / {process.get('name_en')}",
        known_enzymes="",
        known_microbial_enzymes=",".join(t for t in taxa if t),
        input_source="library",
        notes="; ".join(notes_lines),
        library_id=enzyme["id"],
        library_version=str(domain.get("_library_version", "")),
    )


def render_selection_md(
    domain: dict[str, Any],
    process: dict[str, Any],
    enzyme: dict[str, Any],
    card: dict[str, Any],
) -> str:
    taxa_lines = "\n".join(
        f"- **{ex.get('taxon')}** — {ex.get('detail_zh')}"
        for ex in enzyme.get("known_microbial_examples") or []
    )
    entry = enzyme["entry_point"]
    entry_reason = {
        "reaction": "底物-产物关系清楚，先用反应建卡片并按产物反推反应。",
        "ec": "EC 号完整，可以直接用 EC 建卡片并检索参考酶集合。",
        "sequence": "没有可用的 EC 号或没有已表征代表酶，必须从序列 / 结构起手。",
    }[entry]
    return f"""# Target selection / 目标选择记录

## 选择链路

- domain: `{domain['id']}` {domain['name_zh']} / {domain['name_en']}
- process: `{process['id']}` {process['name_zh']} / {process['name_en']}
- enzyme: `{enzyme['id']}` {enzyme['enzyme_name_zh']} / {enzyme['enzyme_name_en']}
- library_version: `{card.get('library_version', '')}`

## 为什么这个过程值得做

{process.get('why_it_matters_zh', '')}

## 这个过程的关键菌

{', '.join(process.get('key_taxa') or [])}

已知的微生物代表：

{taxa_lines or '- （本条目没有列出代表菌）'}

## 筛哪一端

- 推荐起手式：`{entry}` — {entry_reason}
- 目标 EC：`{enzyme.get('ec') or '无 EC 号'}`（ec_confidence = `{enzyme.get('ec_confidence')}`）
- 是否功能暗物质：{'是' if enzyme.get('dark_matter') else '否'}
- 优先级：`{enzyme.get('priority')}`

## 证据状态（必须读）

- `evidence_status` = `{enzyme.get('evidence_status')}`
- `evidence_refs` = {enzyme.get('evidence_refs') or '空'}
- 说明：{enzyme.get('provenance_note_zh', '')}

> 这是策展层面的先验（curated prior），不是已证明的功能。把 `evidence_status` 升级为
> `literature_verified` 之前，必须由 `literature-evidence` 真实检索到 PMID/DOI 并写回
> `evidence_refs`。禁止凭记忆补文献号。

## 可以证伪的验证实验

{enzyme.get('validation_note_zh', '')}

## 下游命令

```bash
# 1. 结构 / 序列筛选前的参考酶集合（用 EC 检索，不要手填登录号）
python3 scripts/fetch_reference_enzymes.py --ec {enzyme.get('ec') or '""'} --out outputs/reference

# 2. 用本卡片进入主流程
python3 scripts/preflight_inputs.py --project projects/<your_project>.json
```
"""


def write_card(card: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "target_function_card.json"
    path.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def export_tsv(index: Index, out_path: Path) -> int:
    rows: list[dict[str, str]] = []
    for domain in index.domains:
        for process in index.iter_processes(domain):
            for enzyme in index.iter_enzymes(domain, process):
                rows.append(
                    {
                        "domain_id": domain["id"],
                        "domain_name_zh": domain["name_zh"],
                        "process_id": process["id"],
                        "process_name_zh": process["name_zh"],
                        "process_name_en": process["name_en"],
                        "process_keywords_zh": ";".join(process.get("keywords_zh") or []),
                        "enzyme_id": enzyme["id"],
                        "enzyme_name_zh": enzyme["enzyme_name_zh"],
                        "enzyme_name_en": enzyme["enzyme_name_en"],
                        "gene_symbols": ";".join(enzyme.get("gene_symbols") or []),
                        "ec": enzyme.get("ec", ""),
                        "ec_confidence": enzyme.get("ec_confidence", ""),
                        "reaction_zh": enzyme.get("reaction_zh", ""),
                        "substrate_zh": enzyme.get("substrate_zh", ""),
                        "product_zh": enzyme.get("product_zh", ""),
                        "cofactor": enzyme.get("cofactor", ""),
                        "fold_hint": enzyme.get("fold_hint", ""),
                        "known_microbial_taxa": ";".join(
                            ex.get("taxon", "") for ex in enzyme.get("known_microbial_examples") or []
                        ),
                        "entry_point": enzyme.get("entry_point", ""),
                        "dark_matter": str(bool(enzyme.get("dark_matter"))),
                        "priority": enzyme.get("priority", ""),
                        "evidence_status": enzyme.get("evidence_status", ""),
                        "evidence_refs": ";".join(enzyme.get("evidence_refs") or []),
                        "validation_note_zh": enzyme.get("validation_note_zh", ""),
                    }
                )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TSV_FIELDS, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return len(rows)


# --------------------------------------------------------------------------
# interactive
# --------------------------------------------------------------------------


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def _choose(items: list[dict[str, Any]], label, title: str) -> dict[str, Any] | None:
    print()
    print(title)
    for i, item in enumerate(items, 1):
        print(f"  {i}) {label(item)}")
    print("  q) 退出")
    while True:
        answer = _ask("请输入编号: ")
        if answer.lower() in {"q", "quit", "exit"}:
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(items):
            return items[int(answer) - 1]
        if not answer:
            return None
        print("  无效编号，请重试。")


def run_interactive(index: Index, out_dir: Path | None, target_id: str | None) -> int:
    if not sys.stdin.isatty():
        print(
            "error: --interactive needs an attached terminal. "
            "Use --search / --list-processes / --show in non-interactive contexts.",
            file=sys.stderr,
        )
        return 2

    domain = _choose(index.domains, render_domain_line, "你是想先确定身体部位 / 生态位：")
    if domain is None:
        print("已退出。")
        return 0

    print()
    print(f"{domain['name_zh']} / {domain['name_en']} — {domain.get('niche_summary_zh', '')}")
    print(f"选择建议：{domain.get('selection_hint_zh', '')}")
    process = _choose(
        list(index.iter_processes(domain)),
        lambda p: f"{p['name_zh']} / {p['name_en']}  —  {p.get('why_it_matters_zh', '')[:60]}…",
        "你关心哪一个生理过程：",
    )
    if process is None:
        print("已退出。")
        return 0

    print()
    print(f"{process['name_zh']} / {process['name_en']}")
    print(f"关键菌：{', '.join(process.get('key_taxa') or [])}")
    enzyme = _choose(
        list(index.iter_enzymes(domain, process)),
        lambda e: (
            f"{e['enzyme_name_zh']} / {e['enzyme_name_en']}  "
            f"EC {e.get('ec') or '无'}  entry_point={e.get('entry_point')}  "
            f"{'暗物质 ' if e.get('dark_matter') else ''}优先级={e.get('priority')}"
        ),
        "要筛哪一个酶：",
    )
    if enzyme is None:
        print("已退出。")
        return 0

    print()
    print(render_process_block(domain, {**process, "enzymes": [enzyme]}, verbose=True))
    confirmed = _ask("按这个目标建卡片？[Y/n]: ").lower()
    if confirmed not in {"", "y", "yes"}:
        print("已取消，未写入任何文件。")
        return 0

    card = build_card_from_enzyme(domain, process, enzyme, target_id=target_id)
    if out_dir is None:
        print()
        print(json.dumps(card, ensure_ascii=False, indent=2))
        return 0
    card_path = write_card(card, out_dir)
    md_path = out_dir / "target_selection.md"
    md_path.write_text(
        render_selection_md(domain, process, enzyme, card), encoding="utf-8"
    )
    print()
    print(f"wrote {card_path}")
    print(f"wrote {md_path}")
    print(
        "下一步：把卡片交给 build-target-function-card 复核字段，然后用 "
        f"entry_point={enzyme['entry_point']} 进入主流程。"
    )
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Browse and search the curated human microbiome target library.",
    )
    parser.add_argument(
        "--library-dir",
        type=Path,
        default=DEFAULT_LIBRARY_DIR,
        help=f"Directory holding <domain>.json library files (default: {DEFAULT_LIBRARY_DIR}).",
    )
    actions = parser.add_argument_group("actions")
    actions.add_argument("--list-domains", action="store_true", help="List available body sites / domains.")
    actions.add_argument(
        "--list-processes",
        metavar="DOMAIN",
        default=None,
        help="List the physiological processes of one domain with their enzyme targets.",
    )
    actions.add_argument(
        "--list-taxa",
        metavar="DOMAIN",
        default=None,
        help="List the taxa worth attention in one domain (or 'all' to merge every domain), with the processes each one drives.",
    )
    actions.add_argument(
        "--show",
        metavar="ID",
        default=None,
        help="Expand a domain id, process id, or enzyme id.",
    )
    actions.add_argument(
        "--search",
        metavar="TEXT",
        default=None,
        help="Natural-language keyword search across domains, processes, and enzymes.",
    )
    actions.add_argument(
        "--interactive",
        action="store_true",
        help="Menu-driven domain -> process -> enzyme selection; writes the card when --output-dir is given.",
    )
    actions.add_argument(
        "--export-card",
        metavar="ENZYME_ID",
        default=None,
        help="Write target_function_card.json (plus target_selection.md) for one enzyme id.",
    )
    actions.add_argument(
        "--export-tsv",
        metavar="PATH",
        default=None,
        help="Flatten the whole library into one tab-separated table for review.",
    )
    actions.add_argument("--validate", action="store_true", help="Audit library content and cross-references.")

    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for generated card files.")
    parser.add_argument("--target-id", default=None, help="Override target_id in the generated card.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of text.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum search hits to print (default 10).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payloads, load_errors = load_library(args.library_dir)
    if load_errors:
        for error in load_errors:
            print(f"error: {error}", file=sys.stderr)
        return 2

    index = Index(payloads)
    did_something = False

    if args.validate:
        did_something = True
        errors = validate_library(payloads)
        if errors:
            print(f"library validation failed with {len(errors)} issue(s):", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 1
        total_process = sum(len(d.get("processes") or []) for d in index.domains)
        total_enzyme = sum(
            len(p.get("enzymes") or []) for d in index.domains for p in d.get("processes") or []
        )
        print(
            f"library OK: {len(index.domains)} domain(s), {total_process} process(es), "
            f"{total_enzyme} enzyme target(s) in {args.library_dir}"
        )

    if args.list_domains:
        did_something = True
        if args.json:
            print(
                json.dumps(
                    [
                        {
                            "id": d["id"],
                            "name_zh": d["name_zh"],
                            "name_en": d["name_en"],
                            "content_status": d.get("content_status"),
                            "role": d.get("role", "shipped_example"),
                            "processes": [p["id"] for p in d.get("processes") or []],
                        }
                        for d in index.domains
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            shipped = [d for d in index.domains if d.get("role", "shipped_example") == "shipped_example"]
            user_made = [d for d in index.domains if d.get("role") == "user_defined"]
            print("Available domains / 可选身体部位：")
            for i, domain in enumerate(index.domains, 1):
                print(f"  {i}) {render_domain_line(domain)}")
            if shipped:
                print()
                print(
                    f"注意：其中 {len(shipped)} 个域（{', '.join(d['id'] for d in shipped)}）是随插件提供的"
                    "示例参考域，用来展示一个靶点应该长什么样，"
                    "不是人体微生物组的覆盖范围。"
                )
                print(
                    "      其他部位（口腔 / 阴道 / 呼吸道 …）不需要库也能做：给出 EC/反应/序列即可走入口 A，"
                    "再用 genome-search 的 --source 挑该部位基因组。"
                )
                print(
                    "      想在这个部位长期工作，用 build_library_domain.py 生成一个 user_defined 域；"
                    "列表里 user_defined 的域会单独标注。"
                )
            if user_made:
                print(f"      你自己添加的域：{', '.join(d['id'] for d in user_made)}")

    if args.list_processes:
        did_something = True
        domain = index.domain(args.list_processes)
        if domain is None:
            print(f"error: unknown domain {args.list_processes!r}", file=sys.stderr)
            return 2
        if args.json:
            print(
                json.dumps(
                    [
                        {
                            "id": p["id"],
                            "name_zh": p["name_zh"],
                            "name_en": p["name_en"],
                            "keywords_zh": p.get("keywords_zh"),
                            "key_taxa": p.get("key_taxa"),
                            "enzymes": [
                                {"id": e["id"], "name_zh": e["enzyme_name_zh"], "ec": e.get("ec"), "entry_point": e.get("entry_point")}
                                for e in p.get("enzymes") or []
                            ],
                        }
                        for p in index.iter_processes(domain)
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(
                f"{domain['name_zh']} / {domain['name_en']}  [{domain.get('content_status')}]  "
                f"library_version={domain.get('_library_version')}"
            )
            print(f"选择建议：{domain.get('selection_hint_zh', '')}")
            for i, process in enumerate(index.iter_processes(domain), 1):
                print()
                block = render_process_block(domain, process, verbose=False)
                first, *rest = block.splitlines()
                print(f"  {i}) {first}")
                for line in rest:
                    print(f"  {line}")

    if args.search:
        did_something = True
        hits = search(index, args.search)
        if args.json:
            print(
                json.dumps(
                    [
                        {
                            "kind": h["kind"],
                            "score": h["score"],
                            "domain": (h.get("domain") or {}).get("id")
                            or ((h.get("records") or [{}])[0].get("domain")),
                            "process": (h.get("process") or {}).get("id"),
                            "enzyme": (h.get("enzyme") or {}).get("id"),
                            "taxon": h.get("taxon"),
                        }
                        for h in hits
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif not hits and looks_like_navigation(args.search):
            print(render_navigation(index, args.search))
            return 0
        elif not hits:
            print(f'no hit for {args.search!r}.')
            print("提示：库里没有命中不代表该功能不存在，只是尚未策展。三条下一步：")
            print(f"      1) 先让路由脚本判断这个问题属于哪种形状：")
            print(f"         python3 scripts/resolve_target_intent.py --query {json.dumps(args.search, ensure_ascii=False)}")
            print(f"      2) 已知目标就直接建档，不经过库：")
            print(f"         python3 scripts/build_target_function_card.py --output outputs/task/target_function_card.json ...")
            print(f"      3) 想长期覆盖这个方向就生成一个 starter 域：")
            print(f"         python3 scripts/build_library_domain.py --init --domain <id> --output specs/<id>.json")
            print("      库里目前覆盖这些方向（--list-processes <domain> 看全部）：")
            for domain in index.domains:
                sample: list[str] = []
                for process in index.iter_processes(domain):
                    sample.append((process.get("keywords_zh") or [process.get("name_zh", "")])[0])
                print(
                    f"        {domain['id']:<6} {domain['name_zh']}: "
                    + ", ".join(sample[:6])
                    + (" …" if len(sample) > 6 else "")
                )
            return 1
        else:
            print(f'{len(hits)} hit(s) for {args.search!r}:')
            for hit in hits[: max(1, args.limit)]:
                print("  " + render_hit(hit))
                if hit["kind"] == "process":
                    for enzyme in hit["process"].get("enzymes") or []:
                        print(
                            f"        -> {enzyme['id']:<38} EC {enzyme.get('ec') or '无':<9} "
                            f"entry_point={enzyme.get('entry_point')}"
                        )
            if len(hits) > args.limit:
                print(f"  … {len(hits) - args.limit} more hit(s); raise --limit to see them.")

    if args.list_taxa:
        did_something = True
        wanted_domains = index.domains
        if args.list_taxa not in {"all", "*"}:
            single = index.domain(args.list_taxa)
            if single is None:
                print(f"error: unknown domain {args.list_taxa!r}", file=sys.stderr)
                return 2
            wanted_domains = [single]
        domain = wanted_domains[0] if len(wanted_domains) == 1 else _merged_taxa_view(index, wanted_domains)
        process_of_taxon: dict[str, list[str]] = {}
        for process in index.iter_processes(domain):
            for name in process.get("key_taxa") or []:
                process_of_taxon.setdefault(name, []).append(process["id"])
        taxa = list(domain.get("focus_taxa") or [])
        order = {"high": 0, "medium": 1, "low": 2}
        taxa.sort(key=lambda t: (order.get(t.get("attention", "low"), 9), t.get("taxon", "")))
        if args.json:
            print(
                json.dumps(
                    [
                        {
                            "taxon": t.get("taxon"),
                            "name_zh": t.get("name_zh"),
                            "attention": t.get("attention"),
                            "role_zh": t.get("role_zh"),
                            "processes": process_of_taxon.get(t.get("taxon", ""), []),
                        }
                        for t in taxa
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(
                f"{domain['name_zh']} / {domain['name_en']} 的值得关注菌 "
                f"（{len(taxa)} 个，按关注度排序）："
            )
            for i, taxon in enumerate(taxa, 1):
                name = taxon.get("taxon", "")
                used = process_of_taxon.get(name) or []
                print()
                owner = f" @ {taxon['_domain']}" if taxon.get("_domain") else ""
                print(
                    f"  {i}) {name}  {taxon.get('name_zh', '')}  "
                    f"[关注度={taxon.get('attention')}]{owner}"
                )
                print(f"     角色：{taxon.get('role_zh', '')}")
                if used:
                    print(f"     在下述过程里是关键菌：{', '.join(used)}")
                else:
                    print("     目前没有绑定到具体过程，可作为背景对照物种。")
            print()
            print("说明：关注度是本库的策展判断，不是文献结论；它回答“先看谁”，不回答“谁已被证明”。")

    if args.show:
        did_something = True
        resolved = index.resolve(args.show)
        if resolved is None:
            print(f"error: {args.show!r} matches no domain, process, or enzyme id", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(resolved, ensure_ascii=False, indent=2, default=str))
        elif resolved["kind"] == "domain":
            domain = resolved["domain"]
            print(render_domain_line(domain))
            print(f"niche: {domain.get('niche_summary_zh', '')}")
            print(f"hint : {domain.get('selection_hint_zh', '')}")
            for process in index.iter_processes(domain):
                print()
                print(render_process_block(domain, process, verbose=True))
        elif resolved["kind"] == "process":
            print(render_process_block(resolved["domain"], resolved["process"], verbose=True))
        else:
            print(render_process_block(resolved["domain"], resolved["process"], verbose=True))

    if args.export_tsv:
        did_something = True
        tsv_path = Path(args.export_tsv)
        count = export_tsv(index, tsv_path)
        print(f"wrote {count} enzyme target row(s) to {tsv_path}")

    if args.export_card:
        did_something = True
        hit = index.find_enzyme(args.export_card)
        if hit is None:
            print(f"error: unknown enzyme id {args.export_card!r}", file=sys.stderr)
            return 2
        domain, process, enzyme = hit
        card = build_card_from_enzyme(domain, process, enzyme, target_id=args.target_id)
        if args.output_dir is None:
            print(json.dumps(card, ensure_ascii=False, indent=2))
        else:
            card_path = write_card(card, args.output_dir)
            md_path = args.output_dir / "target_selection.md"
            md_path.write_text(render_selection_md(domain, process, enzyme, card), encoding="utf-8")
            print(f"wrote {card_path}")
            print(f"wrote {md_path}")

    if args.interactive:
        did_something = True
        return run_interactive(index, args.output_dir, args.target_id)

    if not did_something:
        print(
            "nothing to do. Try --list-domains, --list-processes skin, --search \"油脂分泌\", "
            "--list-taxa skin, --show skin_sebum_lipolysis, --interactive, --export-card, --export-tsv, or --validate.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
