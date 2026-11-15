#!/usr/bin/env python3
"""Rank candidate target enzymes and candidate taxa *before* screening.

This is the pre-screening prioritisation layer. `score_candidates.py` ranks
proteins that already passed sequence/structure screening; this script ranks the
things you are deciding to screen at all:

- which enzyme targets are worth building a project around;
- which taxa are worth downloading genomes for.

It absorbs the scoring model of the local `select-candidate` skill (weighted
sums over human-assigned 0-5 scores) and generalises it from skin to any body
site, while adding the checks that model was missing.

What this script is honest about
--------------------------------
Every component score is **human expert judgement**, not a measurement. The output
therefore carries two trace columns on every row: `score_basis`
(`manual_expert_judgement`) and `scoring_policy` (the exact weights and mix used).
A ranking says "do this first", never "this has the function".

It also refuses to pretend a shortlist exists when it does not: if the configured
threshold is unreachable given the weights and the 0-5 scale, that is an error
rather than an empty `selected` table. (The upstream skill shipped an example
config with `taxa_min_priority_score: 948` against a maximum achievable score of
about 10.6, which silently selected nothing.)

Inputs
------
Enzyme registry (TSV), one row per candidate enzyme target::

    target_id  gene  name  uniprot  ec  site_process  notes
    site_evidence_score  disease_relevance_score  biochemical_clarity_score
    sequence_structure_score  microbial_plausibility_score
    assay_feasibility_score  novelty_score

Taxa registry (TSV), one row per candidate taxon::

    taxon_id  genus  species  display_name  domain  core_tier
    site_presence_score  metabolic_plausibility_score  genome_availability_score
    disease_site_relevance_score  experimental_accessibility_score
    recommended_strain_count  key_evidence_pmids  key_evidence_dois  rationale

`skin_process` / `skin_evidence_score` / `skin_presence_score` are accepted as
aliases, so registries written for the original skin-only skill keep working.

Usage
-----
    # rank using the documented default weights
    python3 scripts/score_target_priorities.py \\
        --enzymes work/enzyme_registry.tsv \\
        --taxa work/taxa_registry.tsv \\
        --output outputs/task/priorities

    # start from the curated library instead of a blank sheet (scores stay empty)
    python3 scripts/score_target_priorities.py \\
        --seed-from-library library/skin.json --output outputs/task/priorities

    # then feed the selected taxa straight into genome search
    python3 skills/genome-search/scripts/genome_source_search.py taxa \\
        --input outputs/task/priorities/selected_taxa.txt --source skin \\
        --out-xlsx work/genome_search/skin.xlsx --out-tsv work/genome_search/skin.tsv
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

SCORE_MAX = 5.0
SCORE_BASIS = "manual_expert_judgement"

DEFAULT_ENZYME_COEFFS = {
    "site_evidence_score": 0.30,
    "disease_relevance_score": 0.25,
    "biochemical_clarity_score": 0.25,
    "sequence_structure_score": 0.20,
}
DEFAULT_DISCOVERY_COEFFS = {
    "microbial_plausibility_score": 0.40,
    "assay_feasibility_score": 0.30,
    "novelty_score": 0.30,
}
DEFAULT_ENZYME_MIX = (0.5, 0.5)  # (known, discovery)
DEFAULT_TAXA_WEIGHTS = {
    "site_presence_score": 0.30,
    "disease_site_relevance_score": 0.25,
    "experimental_accessibility_score": 0.20,
    "genome_availability_score": 0.15,
    "metabolic_plausibility_score": 0.10,
}
DEFAULT_TAXA_MIN_SCORE = 3.0

ENZYME_OUT_FIELDS = [
    "rank",
    "target_id",
    "gene",
    "name",
    "uniprot",
    "ec",
    "site_process",
    "known_score",
    "discovery_score",
    "priority_score",
    "selection_status",
    "site_evidence_score",
    "disease_relevance_score",
    "biochemical_clarity_score",
    "sequence_structure_score",
    "microbial_plausibility_score",
    "assay_feasibility_score",
    "novelty_score",
    "score_basis",
    "scoring_policy",
    "score_sources",
    "notes",
]
TAXA_OUT_FIELDS = [
    "rank",
    "taxon_id",
    "genus",
    "species",
    "display_name",
    "domain",
    "core_tier",
    "priority_score",
    "selection_status",
    "site_presence_score",
    "metabolic_plausibility_score",
    "genome_availability_score",
    "disease_site_relevance_score",
    "experimental_accessibility_score",
    "recommended_strain_count",
    "key_evidence_pmids",
    "key_evidence_dois",
    "score_basis",
    "scoring_policy",
    "score_sources",
    "rationale",
]

PMID_RE = re.compile(r"^\d{1,9}$")
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


# ---------------------------------------------------------------------------
# io helpers
# ---------------------------------------------------------------------------


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def as_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def cell(row: dict[str, str], canonical: str, site: str | None) -> str:
    """Read a column by canonical name, honouring the legacy skin-only aliases."""
    if canonical in row and row[canonical] not in (None, ""):
        return row[canonical]
    for alias in _aliases(canonical, site):
        if alias in row and row[alias] not in (None, ""):
            return row[alias]
    return ""


def _aliases(canonical: str, site: str | None) -> list[str]:
    legacy = []
    if canonical.startswith("site_"):
        rest = canonical[len("site_") :]
        legacy.append("skin_" + rest)
        if site:
            legacy.append(f"{site}_{rest}")
    if canonical == "site_process":
        legacy.extend(["skin_process", "process"])
    return legacy


def score_of(row: dict[str, str], canonical: str, site: str | None, problems: list[str], where: str) -> float:
    raw = cell(row, canonical, site)
    if raw == "":
        problems.append(f"{where}: missing score '{canonical}' (treated as 0)")
        return 0.0
    value = as_float(raw, default=float("nan"))
    if value != value:  # NaN
        problems.append(f"{where}: score '{canonical}' is not a number: {raw!r} (treated as 0)")
        return 0.0
    if value < 0 or value > SCORE_MAX:
        problems.append(f"{where}: score '{canonical}' = {value} is outside 0..{SCORE_MAX:g}")
    return value


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


def load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    if not path.is_file():
        raise SystemExit(f"error: config not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("ranking", data)


def validate_weights(
    cfg: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> tuple[dict[str, float], dict[str, float], float, float, dict[str, float], float]:
    enzyme_c = dict(DEFAULT_ENZYME_COEFFS)
    enzyme_c.update({k: float(v) for k, v in (cfg.get("enzyme_coeffs") or {}).items()})
    discovery_c = dict(DEFAULT_DISCOVERY_COEFFS)
    discovery_c.update({k: float(v) for k, v in (cfg.get("discovery_coeffs") or {}).items()})
    known_w = float(cfg.get("enzyme_known_weight", DEFAULT_ENZYME_MIX[0]))
    discovery_w = float(cfg.get("enzyme_discovery_weight", DEFAULT_ENZYME_MIX[1]))
    taxa_w = dict(DEFAULT_TAXA_WEIGHTS)
    taxa_w.update({k: float(v) for k, v in (cfg.get("taxa_weights") or {}).items()})
    threshold = float(cfg.get("taxa_min_priority_score", DEFAULT_TAXA_MIN_SCORE))

    for name, weights in (
        ("enzyme_coeffs", enzyme_c),
        ("discovery_coeffs", discovery_c),
        ("taxa_weights", taxa_w),
    ):
        total = sum(weights.values())
        if abs(total - 1.0) > 0.01:
            warnings.append(
                f"{name} weights sum to {total:.3f}, not 1.0; the resulting priority_score "
                "is on a different scale than the default, so any threshold must be rescaled too"
            )
        if total <= 0:
            errors.append(f"{name} weights sum to {total}; nothing can ever score above zero")

    if abs((known_w + discovery_w) - 1.0) > 0.01:
        warnings.append(
            f"enzyme_known_weight + enzyme_discovery_weight = {known_w + discovery_w:.3f}, not 1.0"
        )

    max_taxa = SCORE_MAX * sum(taxa_w.values())
    if threshold > max_taxa:
        errors.append(
            f"taxa_min_priority_score = {threshold:g} is unreachable: with these weights and a "
            f"0..{SCORE_MAX:g} score scale the maximum possible value is {max_taxa:.3f}. "
            "Every taxon would be 'defer'. Lower the threshold or rescale the weights."
        )

    return enzyme_c, discovery_c, known_w, discovery_w, taxa_w, threshold


def policy_string(
    enzyme_c: dict[str, float],
    discovery_c: dict[str, float],
    known_w: float,
    discovery_w: float,
) -> str:
    parts = [f"{k}={v:g}" for k, v in sorted(enzyme_c.items())]
    parts += [f"{k}={v:g}" for k, v in sorted(discovery_c.items())]
    parts.append(f"known_weight={known_w:g}")
    parts.append(f"discovery_weight={discovery_w:g}")
    parts.append(f"scale=0..{SCORE_MAX:g}")
    return ";".join(parts)


def taxa_policy_string(taxa_w: dict[str, float], threshold: float) -> str:
    parts = [f"{k}={v:g}" for k, v in sorted(taxa_w.items())]
    parts.append(f"min_score={threshold:g}")
    parts.append(f"scale=0..{SCORE_MAX:g}")
    return ";".join(parts)


# ---------------------------------------------------------------------------
# auto-scoring: derive what the plugin actually has data for, never invent the rest
# ---------------------------------------------------------------------------

RUBRICS = {
    "biochemical_clarity_score": (
        "EC 置信度 full=2 / family=1 / none=0；反应式非空 +1；底物且产物非空 +1；折叠提示非空 +1"
    ),
    "microbial_plausibility_score": (
        "库中已知微生物代表数：0 个=1，1 个=3，≥2 个=4（没有代表不代表不可能，故不给 0）"
    ),
    "novelty_score": "dark_matter=true → 5；无已知微生物代表 → 4；已有代表 → 2",
    "sequence_structure_score": (
        "参考酶集合中该 target 的记录：有结构文件=5；有 UniProt/登录号=3；无记录=0"
    ),
    "genome_availability_score": (
        "genome-search 命中的装配数：0=1，1–3=2，4–9=3，10–19=4，≥20=5；"
        "没有 genome-search 输出时用注册表的 recommended_strain_count（同一分档，auto:registry）"
    ),
    "site_presence_score": (
        "该菌命中装配中直接来源匹配的比例：≥50%=5，>0=4，0=1（需 genome-search 输出含 classification 列）"
    ),
    "site_evidence_score": (
        "literature_evidence.tsv 中该酶 verified=yes 的功能性记录数"
        "（direct_functional_evidence/related_assay）：1 条=3，2 条=4，≥3 条=5；"
        "只有 review 时 1 条=2；无 verified 记录则不推导"
    ),
    "disease_site_relevance_score": (
        "需配合 --literature 与 --disease <表型>：该菌 verified 记录中命中表型的条数，"
        "≥2 条=4，1 条=3；检索过但 0 条命中=1（标为“检索过、无证据”）"
    ),
    "disease_relevance_score": (
        "需配合 --disease <表型>：verified 记录中标题/发现/检索词命中该表型的条数，"
        "≥2 条=4，1 条=3；已检索但 0 条命中=1（并标注为“检索过、无证据”）"
    ),
}

# Which flag makes a currently-missing score derivable, so the failure message can
# say what to run instead of just "fill this in".
DERIVABLE_FROM = {
    "biochemical_clarity_score": "--library <library/<domain>.json>",
    "microbial_plausibility_score": "--library <library/<domain>.json>",
    "novelty_score": "--library <library/<domain>.json>",
    "sequence_structure_score": "--reference-enzymes <reference_enzyme_set.tsv>",
    "genome_availability_score": "--genomes <genome_source_search output.tsv>",
    "site_presence_score": "--genomes <genome_source_search output.tsv>",
    "site_evidence_score": "--literature <literature_evidence.tsv> (verified functional records)",
    "disease_relevance_score": "--literature <literature_evidence.tsv> --disease \"<phenotype>\"",
}

MANUAL_ONLY = {
    "site_evidence_score": "该酶在这个部位是否真的重要：未提供文献表或文献里没有除 review 之外的已验证记录时，只能由你判断",
    "disease_relevance_score": "该酶与目标疾病/表型的关联强度：未提供 --disease 或文献表时，只能由你判断",
    "assay_feasibility_score": "体外测活是否容易：涉及底物可得性、是否需要膜环境等，插件无法判断",
    "metabolic_plausibility_score": "该菌是否具备承担该代谢的合理通路：需要通路分析或领域判断",
    "disease_site_relevance_score": "该菌与目标疾病/部位的关联强度：需要文献/领域判断",
    "experimental_accessibility_score": "该菌是否易培养/可遗传操作：需要菌株知识与生物安全判断",
}


class AutoScorer:
    """Derive the scores that are actually computable from plugin artifacts.

    Anything not derivable stays `manual`, and the caller is told exactly which
    cells are still needed. This class never guesses a score to fill a gap.
    """

    def __init__(
        self,
        library_path: Path | list[Path] | None,
        reference_path: Path | None,
        genomes_path: Path | None,
        literature_path: Path | None = None,
        disease: str | None = None,
    ) -> None:
        self.enzyme_facts: dict[str, dict[str, Any]] = {}
        # focus_taxa from the library say which organisms a curated process actually implicates;
        # that is the only library-derived signal a taxon ranking can legitimately use.
        self.taxa_focus: dict[str, str] = {}
        self.reference_rows: dict[str, list[dict[str, str]]] = {}
        self.taxa_stats: dict[str, dict[str, Any]] = {}
        self.sources_loaded: list[str] = []
        self.disease = (disease or "").strip()
        self.literature_rows: list[dict[str, str]] = []
        self.literature_used: dict[str, list[str]] = {}
        if literature_path is not None and literature_path.is_file():
            self.literature_rows = read_tsv(literature_path)
            self.sources_loaded.append(f"literature={literature_path.name}")

        library_paths: list[Path] = []
        if isinstance(library_path, (list, tuple)):
            library_paths = [p for p in library_path if p is not None]
        elif library_path is not None:
            library_paths = [library_path]
        for path in library_paths:
            if not path.is_file():
                raise SystemExit(f"error: library not found: {path}")
            payload = json.loads(path.read_text(encoding="utf-8"))
            for process in (payload.get("domain") or {}).get("processes") or []:
                for enzyme in process.get("enzymes") or []:
                    self.enzyme_facts[enzyme.get("id", "")] = enzyme
            for taxon in (payload.get("domain") or {}).get("focus_taxa") or []:
                name = str(taxon.get("taxon") or "").strip()
                attention = str(taxon.get("attention") or "").strip().lower()
                if name:
                    self.taxa_focus[name] = attention
            self.sources_loaded.append(f"library={path.name}")

        if reference_path is not None and reference_path.is_file():
            for row in read_tsv(reference_path):
                self.reference_rows.setdefault(row.get("target_id", ""), []).append(row)
            self.sources_loaded.append(f"reference_enzymes={reference_path.name}")

        if genomes_path is not None and genomes_path.is_file():
            for row in read_tsv(genomes_path):
                name = (row.get("input") or row.get("organism") or "").strip()
                if not name:
                    continue
                stats = self.taxa_stats.setdefault(name, {"n": 0, "direct": 0})
                stats["n"] += 1
                classification = (row.get("classification") or "").lower()
                if "direct" in classification:
                    stats["direct"] += 1
            self.sources_loaded.append(f"genomes={genomes_path.name}")

    # -- enzymes ---------------------------------------------------------
    def enzyme_scores(self, target_id: str, row: dict[str, str]) -> dict[str, tuple[float, str]]:
        facts = self.enzyme_facts.get(target_id)
        out: dict[str, tuple[float, str]] = {}
        if facts is not None:
            confidence = facts.get("ec_confidence", "none")
            clarity = {"full": 2.0, "family": 1.0}.get(confidence, 0.0)
            if facts.get("reaction_zh"):
                clarity += 1
            if facts.get("substrate_zh") and facts.get("product_zh"):
                clarity += 1
            if facts.get("fold_hint"):
                clarity += 1
            out["biochemical_clarity_score"] = (min(clarity, SCORE_MAX), "auto:library")

            examples = len(facts.get("known_microbial_examples") or [])
            plausibility = 1.0 if examples == 0 else (3.0 if examples == 1 else 4.0)
            out["microbial_plausibility_score"] = (plausibility, "auto:library")

            if facts.get("dark_matter"):
                novelty = 5.0
            elif examples == 0:
                novelty = 4.0
            else:
                novelty = 2.0
            out["novelty_score"] = (novelty, "auto:library")

            # Evidence strength has to count. Without it a target that merely carries an EC
            # outranks the only entry the literature actually supports, which is exactly backwards
            # for "which candidate should I work on first".
            status = str(facts.get("evidence_status") or "").strip()
            ref_count = len(facts.get("evidence_refs") or [])
            if status == "literature_verified" and ref_count >= 2:
                site_score = 5.0
            elif status == "literature_verified":
                site_score = 4.0
            elif ref_count:
                site_score = 2.0     # references retrieved, but not sufficient for the claim
            else:
                # curated prior with no references is UNKNOWN, not "low evidence". Leaving it
                # unset keeps the distinction the whole plugin depends on.
                site_score = None
            if site_score is not None:
                out["site_evidence_score"] = (site_score, "auto:library")

        # A registry produced by the discovery route records two things the library does not:
        # whether the retrieved text named an EC for this enzyme, and whether the text was about
        # microbiome metabolism at all. Both are derivable without inventing anything.
        if facts is None:
            ec_confidence = str(row.get("ec_confidence") or "").strip().lower()
            if ec_confidence in ("full", "family"):
                clarity = 2.0 if ec_confidence == "full" else 1.5
                out["biochemical_clarity_score"] = (clarity, "auto:registry")
            if str(row.get("microbial_context") or "").strip().lower() in ("yes", "true", "1"):
                # named in an abstract about microbial xenobiotic metabolism: plausible for a
                # microbe to carry it, but not demonstrated for a named protein
                out["microbial_plausibility_score"] = (3.0, "auto:registry")

        out.update(self._literature_scores(target_id, facts))

        refs = self.reference_rows.get(target_id) or []
        if refs:
            if any(r.get("structure_file") for r in refs):
                out["sequence_structure_score"] = (5.0, "auto:reference_enzymes")
            elif any((r.get("uniprot") or r.get("reference_id")) for r in refs):
                out["sequence_structure_score"] = (3.0, "auto:reference_enzymes")
            else:
                out["sequence_structure_score"] = (1.0, "auto:reference_enzymes")
        return out

    # -- literature ------------------------------------------------------
    def _literature_for(self, target_id: str, facts: dict[str, Any] | None) -> list[dict[str, str]]:
        """Rows that are plausibly about this target.

        Three routes, in decreasing strength: candidate_id equality,
        reference-enzyme accession match, and the enzyme name appearing in the
        title/finding text. Text matching is the weakest and requires a name of
        at least four characters so short symbols cannot match everything.
        """
        if not self.literature_rows:
            return []
        accessions: set[str] = set()
        for row in self.reference_rows.get(target_id) or []:
            for key in ("reference_id", "uniprot"):
                value = (row.get(key) or "").strip()
                if value:
                    accessions.add(value.split(".")[0])
        name = ""
        if facts is not None:
            name = (facts.get("enzyme_name_en") or "").strip()
        matched: list[dict[str, str]] = []
        for row in self.literature_rows:
            candidate = (row.get("candidate_id") or "").strip()
            accession = (row.get("protein_accession") or "").strip()
            if candidate and candidate == target_id:
                matched.append(row)
                continue
            if accession and accession.split(".")[0] in accessions:
                matched.append(row)
                continue
            if len(name) >= 4:
                haystack = f"{row.get('title', '')} {row.get('finding', '')}".lower()
                if name.lower() in haystack:
                    matched.append(row)
        return matched

    def _literature_scores(
        self, target_id: str, facts: dict[str, Any] | None
    ) -> dict[str, tuple[float, str]]:
        rows = self._literature_for(target_id, facts)
        out: dict[str, tuple[float, str]] = {}
        if not rows:
            return out

        def verified(row: dict[str, str]) -> bool:
            return (row.get("verified") or "").strip().lower() in {"yes", "true", "1", "y"}

        strong = [
            row
            for row in rows
            if verified(row)
            and (row.get("evidence_type") or "").strip()
            in {"direct_functional_evidence", "related_assay"}
        ]
        reviews = [
            row
            for row in rows
            if verified(row) and (row.get("evidence_type") or "").strip() == "review"
        ]
        if len(strong) >= 3:
            out["site_evidence_score"] = (5.0, "auto:literature")
        elif len(strong) == 2:
            out["site_evidence_score"] = (4.0, "auto:literature")
        elif len(strong) == 1:
            out["site_evidence_score"] = (3.0, "auto:literature")
        elif reviews:
            out["site_evidence_score"] = (2.0, "auto:literature")
        # Unverified rows and explicit no_evidence rows establish nothing, so the
        # score stays a gap rather than becoming a low number.

        if self.disease:
            term = self.disease.lower()
            hits = [
                row
                for row in rows
                if verified(row)
                and term
                in f"{row.get('title', '')} {row.get('finding', '')} {row.get('source_search', '')}".lower()
                and (row.get("evidence_type") or "").strip() != "no_evidence"
            ]
            usable = [
                row
                for row in rows
                if verified(row)
                and (row.get("evidence_type") or "").strip() not in {"", "no_evidence"}
            ]
            if len(hits) >= 2:
                out["disease_relevance_score"] = (4.0, "auto:literature")
            elif len(hits) == 1:
                out["disease_relevance_score"] = (3.0, "auto:literature")
            elif usable:
                # The search produced usable records, none of which tie this target
                # to the phenotype. That is a real (if weak) negative signal.
                out["disease_relevance_score"] = (1.0, "auto:literature:no_match")
            # With no usable verified record at all, "no link to the disease" cannot
            # be concluded — the cell stays a gap instead of becoming a 1.

        refs = []
        for row in rows[:5]:
            ref_id = (row.get("reference_id") or "").strip()
            kind = (row.get("evidence_type") or "").strip()
            flag = "verified" if verified(row) else "unverified"
            if ref_id:
                refs.append(f"{ref_id}({kind or '?'},{flag})")
        if refs:
            self.literature_used[target_id] = refs
        return out

    # -- taxa ------------------------------------------------------------
    def _taxon_literature_rows(
        self, genus: str, species: str, row: dict[str, str] | None
    ) -> list[dict[str, str]]:
        """Literature rows that plausibly concern this taxon.

        Matching on the organism column keeps this usable without inventing identifiers; the
        taxon_id is accepted too so a registry that shares ids with the evidence table still joins.
        """
        organism = f"{genus} {species}".strip().lower()
        species_l = species.strip().lower()
        taxon_id = ((row or {}).get("taxon_id") or "").strip().lower()
        out: list[dict[str, str]] = []
        for entry in self.literature_rows:
            org = (entry.get("organism_or_strain") or "").lower()
            cid = (entry.get("candidate_id") or "").strip().lower()
            if (organism and organism in org) or (species_l and species_l in org) or (taxon_id and cid == taxon_id):
                out.append(entry)
        return out

    def taxa_scores(
        self, genus: str, species: str, row: dict[str, str] | None = None
    ) -> dict[str, tuple[float, str]]:
        out: dict[str, tuple[float, str]] = {}
        binomial = f"{genus} {species}".strip()
        if binomial in self.taxa_focus:
            attention = self.taxa_focus[binomial]
            plausibility = {"high": 4.0, "medium": 3.0, "low": 2.0}.get(attention, 2.0)
            out["metabolic_plausibility_score"] = (plausibility, "auto:library")
        candidates = [binomial, species.strip(), genus.strip()]
        stats = None
        for key in candidates:
            if key and key in self.taxa_stats:
                stats = self.taxa_stats[key]
                break
        if stats is None:
            return out
        n = stats["n"]
        if n >= 20:
            availability = 5.0
        elif n >= 10:
            availability = 4.0
        elif n >= 4:
            availability = 3.0
        elif n >= 1:
            availability = 2.0
        else:
            availability = 1.0
        out["genome_availability_score"] = (availability, "auto:genome_search")
        if stats["direct"]:
            ratio = stats["direct"] / n
            out["site_presence_score"] = (5.0 if ratio >= 0.5 else 4.0, "auto:genome_search")
        else:
            out["site_presence_score"] = (1.0, "auto:genome_search")
        return out

    def _taxa_extra_scores(
        self, genus: str, species: str, row: dict[str, str] | None
    ) -> dict[str, tuple[float, str]]:
        """Scores derivable without a genome-search run.

        Two of the five taxa components were previously `missing` even when the registry already
        carried the answer: the species list states how many assemblies it recommends, and the
        literature table says whether the species has been studied in the disease being asked about.
        Leaving them blank made every shortlist look thinner than its own inputs.
        """
        out: dict[str, tuple[float, str]] = {}
        data = row or {}

        raw_count = (data.get("recommended_strain_count") or "").strip()
        if raw_count:
            try:
                count = int(float(raw_count))
            except ValueError:
                count = None
            if count is not None:
                if count >= 20:
                    value = 5.0
                elif count >= 10:
                    value = 4.0
                elif count >= 4:
                    value = 3.0
                elif count >= 1:
                    value = 2.0
                else:
                    value = 1.0
                out["genome_availability_score"] = (value, "auto:registry")

        if self.disease:
            rows = self._taxon_literature_rows(genus, species, row)
            if rows:
                term = self.disease.lower()
                verified = [
                    entry
                    for entry in rows
                    if (entry.get("verified") or "").strip().lower() in {"yes", "true", "1", "y"}
                ]
                hits = [
                    entry
                    for entry in verified
                    if term
                    in " ".join(
                        [
                            entry.get("title", ""),
                            entry.get("finding", ""),
                            entry.get("source_search", ""),
                            entry.get("notes", ""),
                        ]
                    ).lower()
                ]
                if len(hits) >= 2:
                    out["disease_site_relevance_score"] = (4.0, "auto:literature")
                elif len(hits) == 1:
                    out["disease_site_relevance_score"] = (3.0, "auto:literature")
                elif verified:
                    out["disease_site_relevance_score"] = (1.0, "auto:literature:no_match")
        return out


def resolve_score(
    row: dict[str, str],
    key: str,
    site: str | None,
    auto: dict[str, tuple[float, str]],
    sources: dict[str, str],
    problems: list[str],
    where: str,
) -> float:
    """Manual value wins; otherwise an auto-derived value; otherwise a gap."""
    raw = cell(row, key, site)
    if raw != "":
        sources[key] = "manual"
        return score_of(row, key, site, problems, where)
    if key in auto:
        value, source = auto[key]
        sources[key] = source
        return value
    sources[key] = "missing"
    problems.append(f"{where}: '{key}' has no value and cannot be derived")
    return 0.0


# ---------------------------------------------------------------------------
# ranking
# ---------------------------------------------------------------------------


def gate_row(
    sources: dict[str, str],
    min_criteria: int | None,
    min_evidence: int | None,
) -> tuple[bool, str]:
    """Decide whether a row carries enough backing to be ranked at all.

    Two separate questions, because conflating them is how a made-up score sneaks in:

    - min_criteria: how many components have any value (manual judgement counts);
    - min_evidence: how many components were DERIVED from data (auto:*), which is the
      only kind of backing that is not just someone's opinion.
    """
    backed = sum(1 for source in sources.values() if source != "missing")
    derived = sum(1 for source in sources.values() if source.startswith("auto:"))
    if min_criteria is not None and backed < min_criteria:
        return False, (
            f"only {backed} of {len(sources)} components have a value "
            f"({min_criteria} required)"
        )
    if min_evidence is not None and derived < min_evidence:
        return False, (
            f"only {derived} of {len(sources)} components are data-derived "
            f"({min_evidence} required); the rest are judgement or missing"
        )
    return True, f"{backed}/{len(sources)} components backed, {derived} data-derived"


def rank_enzymes(
    rows: list[dict[str, str]],
    enzyme_c: dict[str, float],
    discovery_c: dict[str, float],
    known_w: float,
    discovery_w: float,
    site: str | None,
    problems: list[str],
    auto_scorer: AutoScorer | None = None,
    min_criteria: int | None = None,
    min_evidence: int | None = None,
    withheld: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    policy = policy_string(enzyme_c, discovery_c, known_w, discovery_w)
    ranked: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        target_id = row.get("target_id", "") or f"row{index}"
        where = f"enzyme[{target_id}]"
        auto = auto_scorer.enzyme_scores(target_id, row) if auto_scorer else {}
        sources: dict[str, str] = {}
        values: dict[str, float] = {}
        for key in list(enzyme_c) + list(discovery_c):
            values[key] = resolve_score(row, key, site, auto, sources, problems, where)
        known = sum(weight * values[key] for key, weight in enzyme_c.items())
        discovery = sum(weight * values[key] for key, weight in discovery_c.items())
        passes, reason = gate_row(sources, min_criteria, min_evidence)
        if not passes and withheld is not None:
            withheld.append(
                {
                    "table": "enzyme_priority_ranking",
                    "id": target_id,
                    "name": cell(row, "name", site),
                    "reason": reason,
                    "priority_score": f"{known_w * known + discovery_w * discovery:.3f}",
                }
            )
        ranked.append(
            {
                "target_id": target_id,
                "selection_status": "ranked" if passes else "insufficient_evidence",
                "_passes": passes,
                "gene": cell(row, "gene", site),
                "name": cell(row, "name", site),
                "uniprot": cell(row, "uniprot", site),
                "ec": cell(row, "ec", site),
                "site_process": cell(row, "site_process", site),
                "known_score": f"{known:.3f}",
                "discovery_score": f"{discovery:.3f}",
                "priority_score": f"{known_w * known + discovery_w * discovery:.3f}",
                "score_basis": SCORE_BASIS,
                "scoring_policy": policy,
                "score_sources": ";".join(f"{k}={v}" for k, v in sorted(sources.items())),
                "notes": cell(row, "notes", site),
                **{key: f"{values[key]:.3f}" for key in values},
            }
        )
    return _finalise_ranks(ranked)


def _finalise_ranks(ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows that failed the gate keep no rank, so they cannot be read as ordered.

    They stay in the table on purpose: hiding them would make the output look complete
    when the evidence was not.
    """
    ranked.sort(
        key=lambda r: (
            -float(r["priority_score"]),
            str(r.get("target_id") or r.get("taxon_id") or ""),
        )
    )
    passing = [row for row in ranked if row.get("_passes", True)]
    failing = [row for row in ranked if not row.get("_passes", True)]
    ordered = passing + failing
    for i, row in enumerate(passing, 1):
        row["rank"] = i
    for row in failing:
        row["rank"] = ""
    for row in ordered:
        row.pop("_passes", None)
    return ordered


def rank_taxa(
    rows: list[dict[str, str]],
    taxa_w: dict[str, float],
    threshold: float,
    site: str | None,
    problems: list[str],
    warnings: list[str],
    auto_scorer: AutoScorer | None = None,
    min_criteria: int | None = None,
    min_evidence: int | None = None,
    withheld: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    policy = taxa_policy_string(taxa_w, threshold)
    ranked: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        taxon_id = row.get("taxon_id", "") or f"row{index}"
        where = f"taxa[{taxon_id}]"
        genus = cell(row, "genus", site)
        species = cell(row, "species", site)
        auto = auto_scorer.taxa_scores(genus, species, row) if auto_scorer else {}
        if auto_scorer:
            for key, value in auto_scorer._taxa_extra_scores(genus, species, row).items():
                auto.setdefault(key, value)  # genome-search output wins when both exist
        sources: dict[str, str] = {}
        values: dict[str, float] = {}
        for key in taxa_w:
            values[key] = resolve_score(row, key, site, auto, sources, problems, where)
        total = sum(weight * values[key] for key, weight in taxa_w.items())
        pmids = cell(row, "key_evidence_pmids", site)
        dois = cell(row, "key_evidence_dois", site)
        for pmid in _split_refs(pmids):
            if not PMID_RE.match(pmid):
                warnings.append(
                    f"{where}: '{pmid}' is not a bare PMID; this script does not verify it, "
                    "so keep only identifier text you actually retrieved"
                )
        for doi in _split_refs(dois):
            if not DOI_RE.match(doi):
                warnings.append(
                    f"{where}: '{doi}' does not look like a DOI; this script does not verify it"
                )
        passes, reason = gate_row(sources, min_criteria, min_evidence)
        if not passes:
            if withheld is not None:
                withheld.append(
                    {
                        "table": "taxa_priority_ranking",
                        "id": taxon_id,
                        "name": f"{genus} {species}".strip(),
                        "reason": reason,
                        "priority_score": f"{total:.3f}",
                    }
                )
        ranked.append(
            {
                "taxon_id": taxon_id,
                "selection_status": (
                    ("selected" if total >= threshold else "defer") if passes
                    else "insufficient_evidence"
                ),
                "_passes": passes,
                "genus": genus,
                "species": species,
                "display_name": cell(row, "display_name", site),
                "domain": cell(row, "domain", site),
                "core_tier": cell(row, "core_tier", site),
                "priority_score": f"{total:.3f}",
                "recommended_strain_count": cell(row, "recommended_strain_count", site),
                "key_evidence_pmids": pmids,
                "key_evidence_dois": dois,
                "score_basis": SCORE_BASIS,
                "scoring_policy": policy,
                "score_sources": ";".join(f"{k}={v}" for k, v in sorted(sources.items())),
                "rationale": cell(row, "rationale", site),
                **{key: f"{values[key]:.3f}" for key in values},
            }
        )
    return _finalise_ranks(ranked)


def _split_refs(value: str) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in re.split(r"[;,]", value) if part.strip()]


# ---------------------------------------------------------------------------
# seeding from the curated library
# ---------------------------------------------------------------------------


def seed_from_library(library_path: Path, site: str | None) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    payload = json.loads(library_path.read_text(encoding="utf-8"))
    domain = payload.get("domain") or {}
    enzyme_rows: list[dict[str, str]] = []
    taxa_rows: list[dict[str, str]] = []
    for process in domain.get("processes") or []:
        for enzyme in process.get("enzymes") or []:
            enzyme_rows.append(
                {
                    "target_id": enzyme.get("id", ""),
                    "gene": (enzyme.get("gene_symbols") or [""])[0],
                    "name": enzyme.get("enzyme_name_en", ""),
                    "uniprot": "",
                    "ec": enzyme.get("ec", ""),
                    "site_process": process.get("name_en", ""),
                    "notes": enzyme.get("provenance_note_zh", ""),
                }
            )
    for taxon in domain.get("focus_taxa") or []:
        name = taxon.get("taxon", "")
        parts = name.split()
        taxa_rows.append(
            {
                "taxon_id": re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_"),
                "genus": parts[0] if parts else "",
                "species": " ".join(parts[1:]) if len(parts) > 1 else "",
                "display_name": taxon.get("name_zh", "") or name,
                "domain": "",
                "core_tier": taxon.get("attention", ""),
                "recommended_strain_count": "",
                "key_evidence_pmids": "",
                "key_evidence_dois": "",
                "rationale": taxon.get("role_zh", ""),
            }
        )
    del site  # the library already encodes the site
    return enzyme_rows, taxa_rows


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def render_report(
    enzyme_rows: list[dict[str, Any]],
    taxa_rows: list[dict[str, Any]],
    threshold: float,
    site: str | None,
    seeded_from: Path | None,
    problems: list[str],
    warnings: list[str],
    literature_used: dict[str, list[str]] | None = None,
    disease: str | None = None,
) -> str:
    lines = ["# Candidate prioritisation before screening", ""]
    lines.append(
        "这份表回答的是「先做谁」，不是「谁有功能」。每个分项分数都是**人工判断**"
        f"（`score_basis = {SCORE_BASIS}`），不是实验测量。"
    )
    if seeded_from is not None:
        lines.append("")
        lines.append(
            f"本次表由目标库 `{seeded_from}` 生成骨架，**分项分数全部留空**，"
            "需要你按 0–5 自己打分后再跑一次。脚本不会替你编分数。"
        )
    lines.append("")
    if enzyme_rows:
        lines.append("## 酶目标排序（前 10）")
        lines.append("")
        lines.append("| rank | target_id | 名称 | EC | 过程 | priority | known | discovery |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for row in enzyme_rows[:10]:
            lines.append(
                f"| {row['rank']} | {row['target_id']} | {row['name']} | {row['ec']} | "
                f"{row['site_process']} | {row['priority_score']} | {row['known_score']} | "
                f"{row['discovery_score']} |"
            )
        lines.append("")
        top = enzyme_rows[0]
        lines.append(
            f"排序第一的是 `{top['target_id']}`。如果它的分数与第二名差距很小，"
            "说明这份打分还不足以支撑选择——先复核打分而非直接开工。"
        )
        lines.append("")
        lines.append("下一步（入口 A）：")
        lines.append("")
        lines.append("```bash")
        lines.append(
            f"python3 scripts/build_target_function_card.py --output outputs/task/target_function_card.json "
            f"--ec {top['ec'] or '<EC>'} --enzyme-name \"{top['name']}\" --input-source ec"
        )
        lines.append("```")
        lines.append("")
    if taxa_rows:
        selected = [r for r in taxa_rows if r["selection_status"] == "selected"]
        lines.append("## 菌株排序")
        lines.append("")
        lines.append(f"阈值 `{threshold:g}`，入选 {len(selected)} / {len(taxa_rows)} 个。")
        lines.append("")
        lines.append("| rank | taxon | 中文名 | core_tier | priority | 状态 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for row in taxa_rows:
            lines.append(
                f"| {row['rank']} | {row['genus']} {row['species']} | {row['display_name']} | "
                f"{row['core_tier']} | {row['priority_score']} | {row['selection_status']} |"
            )
        lines.append("")
        if selected:
            source_flag = f"--source {site} " if site else "--source <skin|oral|gut|respiratory|urogenital|blood|environment> "
            lines.append("下一步：把入选菌株直接交给基因组检索。")
            lines.append("")
            lines.append("```bash")
            lines.append(
                "python3 skills/genome-search/scripts/genome_source_search.py taxa "
                f"--input selected_taxa.txt {source_flag}"
                "--out-xlsx work/genome_search/selected.xlsx --out-tsv work/genome_search/selected.tsv"
            )
            lines.append("```")
        else:
            lines.append(
                "**没有任何菌株入选。** 这通常是阈值或权重设置的问题，不是「没有值得做的菌」。"
                "先看下面 warnings，再调低阈值或重设权重。"
            )
        lines.append("")
    # score provenance: what was derived, what the user had to judge
    auto_used: dict[str, set[str]] = {}
    manual_used: set[str] = set()
    missing_used: set[str] = set()
    for row in list(enzyme_rows) + list(taxa_rows):
        for part in str(row.get("score_sources", "")).split(";"):
            if "=" not in part:
                continue
            key, source = part.split("=", 1)
            if source.startswith("auto:"):
                auto_used.setdefault(key, set()).add(source.split(":", 1)[1])
            elif source == "manual":
                manual_used.add(key)
            elif source == "missing":
                missing_used.add(key)
    if auto_used:
        lines.append("## 自动推导的分数（可复算）")
        lines.append("")
        lines.append("| 分项 | 依据 | 数据源 |")
        lines.append("| --- | --- | --- |")
        for key in sorted(auto_used):
            lines.append(
                f"| {key} | {RUBRICS.get(key, '规则见脚本')} | {', '.join(sorted(auto_used[key]))} |"
            )
        lines.append("")
    if manual_used:
        lines.append("## 必须由你判断的分数（插件无数据源）")
        lines.append("")
        for key in sorted(manual_used):
            lines.append(f"- `{key}`：{MANUAL_ONLY.get(key, '需要外部判断')}")
        lines.append("")
    if missing_used:
        lines.append("## 缺失且未推导的分数（按 0 计入）")
        lines.append("")
        for key in sorted(missing_used):
            lines.append(f"- `{key}`：既没有给值，也无法从现有产物推导")
        lines.append("")
        lines.append(
            "这些项按 0 参与加权，会系统性压低相关候选的排名——不要把 `--allow-missing-scores` "
            "产出的排名当作结论。"
        )
        lines.append("")

    if literature_used:
        lines.append("## 文献依据（用于 site_evidence / disease_relevance）")
        lines.append("")
        if disease:
            lines.append(f"表型检索词：`{disease}`。命中指该词出现在标题、发现或检索式里。")
            lines.append("")
        lines.append("| target | 参与计数的 references（最多 5 条） |")
        lines.append("| --- | --- |")
        for target_id in sorted(literature_used):
            lines.append(f"| {target_id} | {', '.join(literature_used[target_id])} |")
        lines.append("")
        lines.append(
            "计分规则：只算 `verified=yes` 的记录。`direct_functional_evidence` / "
            "`related_assay` 才算功能性证据；只有 `review` 时给到 2 分；"
            "`no_evidence` 或未核实记录不抬高分数——它们连“有证据”都不算。"
        )
        lines.append("")
        if disease:
            lines.append(
                "**注意**：`disease_relevance_score` 统计的是文献里同时提到该酶与该表型的记录数，"
                "属于共现证据，不等于因果或机制关联。需要机制判断时请看具体文献结论。"
            )
            lines.append("")

    withheld_rows = [row for row in (enzyme_rows or []) + (taxa_rows or [])
                     if row.get("selection_status") == "insufficient_evidence"]
    if withheld_rows:
        lines.append("## 因证据不足而被扣下的行")
        lines.append("")
        lines.append(
            f"{len(withheld_rows)} 行的已填分项少于门槛，因此**不给名次**（rank 留空）。"
            "它们仍留在表里：隐藏掉会让输出看起来完整，而证据其实不够。"
        )
        lines.append("")
        lines.append("| 表 | 对象 |")
        lines.append("| --- | --- |")
        for row in withheld_rows[:20]:
            label = row.get("taxon_id") or row.get("target_id")
            lines.append(f"| {'taxa' if row.get('taxon_id') else 'enzyme'} | {label} |")
        if len(withheld_rows) > 20:
            lines.append(f"| ... | 还有 {len(withheld_rows) - 20} 行 |")
        lines.append("")

    # A ranking where everyone ties is not a ranking; say so instead of implying order.
    for label, rows in (("菌株", taxa_rows), ("酶目标", enzyme_rows)):
        if len(rows) < 4:
            continue
        distinct = {row["priority_score"] for row in rows}
        if len(distinct) <= max(2, len(rows) // 10):
            lines.append("## 注意：这份排名几乎是并列的")
            lines.append("")
            lines.append(
                f"{label}共 {len(rows)} 条，但只有 {len(distinct)} 个不同的总分。"
                "原因是多数分项既没有给值也无法推导，权重被留空的项吃掉——"
                "名次差异基本只来自少数已填分项。补齐其他分项（或提供 --genomes / "
                "--literature / --library 让它们可推导）之前，不要把这个顺序当结论。"
            )
            lines.append("")

    lines.append("## 边界")
    lines.append("")
    lines.append("- 分项分数由人给，不同人打分可能不一样；换一套分数排名就会变。")
    lines.append("- 排名只用于**决定先做谁**，不能当作功能证据，也不能写进结论。")
    lines.append("- `selected` 只表示「值得先下载它的基因组」，不表示「它一定参与这个功能」。")
    lines.append("- `key_evidence_pmids` / `key_evidence_dois` 原样透传，本脚本**不核实**，也不补全。")
    lines.append("")
    if problems:
        lines.append("## Problems")
        lines.append("")
        for item in problems:
            lines.append(f"- {item}")
        lines.append("")
    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for item in warnings:
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rank candidate target enzymes and candidate taxa before screening.",
    )
    parser.add_argument("--enzymes", type=Path, default=None, help="Enzyme registry TSV.")
    parser.add_argument("--taxa", type=Path, default=None, help="Taxa registry TSV.")
    parser.add_argument("--config", type=Path, default=None, help="Optional ranking config JSON.")
    parser.add_argument(
        "--seed-from-library",
        type=Path,
        default=None,
        help="Write registry skeletons from a library/<domain>.json instead of ranking; scores stay empty.",
    )
    parser.add_argument("--output", type=Path, required=True, help="Output directory.")
    parser.add_argument("--site", default=None, help="Body site id used for legacy column aliases (skin, gut, oral ...).")
    parser.add_argument("--min-taxa-score", type=float, default=None, help="Override the taxa selection threshold.")
    parser.add_argument(
        "--auto-score",
        action="store_true",
        help="Derive the scores that are computable from plugin artifacts; leave the rest as gaps instead of guessing.",
    )
    parser.add_argument(
        "--require-min-criteria",
        type=int,
        default=None,
        metavar="N",
        help="Withhold rows with fewer than N backed components (manual judgement counts).",
    )
    parser.add_argument(
        "--require-min-evidence",
        type=int,
        default=None,
        metavar="N",
        help="Withhold rows with fewer than N DATA-DERIVED components (auto:* only, not judgement).",
    )
    parser.add_argument(
        "--library",
        type=Path,
        action="append",
        default=None,
        help="library/<domain>.json providing per-enzyme facts for --auto-score. Repeatable: "
             "passing only the last of several libraries silently zeroed every other domain's "
             "auto-derived components.",
    )
    parser.add_argument("--reference-enzymes", type=Path, default=None, help="reference_enzyme_set.tsv for sequence_structure_score.")
    parser.add_argument("--genomes", type=Path, default=None, help="genome_source_search *.tsv for taxa genome/site scores.")
    parser.add_argument(
        "--literature",
        type=Path,
        default=None,
        help="literature_evidence.tsv; lets site_evidence_score and disease_relevance_score be derived from verified records.",
    )
    parser.add_argument(
        "--disease",
        default=None,
        help="Phenotype/disease term used to derive disease_relevance_score from the literature table.",
    )
    parser.add_argument(
        "--allow-missing-scores",
        action="store_true",
        help="Rank even when some scores could be neither given nor derived (they count as 0).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)

    if args.seed_from_library is not None:
        if not args.seed_from_library.is_file():
            print(f"error: library file not found: {args.seed_from_library}", file=sys.stderr)
            return 2
        enzyme_rows, taxa_rows = seed_from_library(args.seed_from_library, args.site)
        enzyme_path = args.output / "enzyme_registry.seed.tsv"
        taxa_path = args.output / "taxa_registry.seed.tsv"
        write_tsv(
            enzyme_path,
            enzyme_rows,
            ["target_id", "gene", "name", "uniprot", "ec", "site_process", "notes"]
            + list(DEFAULT_ENZYME_COEFFS)
            + list(DEFAULT_DISCOVERY_COEFFS),
        )
        write_tsv(
            taxa_path,
            taxa_rows,
            ["taxon_id", "genus", "species", "display_name", "domain", "core_tier",
             "recommended_strain_count", "key_evidence_pmids", "key_evidence_dois", "rationale"]
            + list(DEFAULT_TAXA_WEIGHTS),
        )
        report = render_report([], [], DEFAULT_TAXA_MIN_SCORE, args.site, args.seed_from_library, [], [])
        (args.output / "ranking_report.md").write_text(report, encoding="utf-8")
        print(f"wrote {enzyme_path} ({len(enzyme_rows)} enzyme rows, scores empty)")
        print(f"wrote {taxa_path} ({len(taxa_rows)} taxa rows, scores empty)")
        print(f"wrote {args.output / 'ranking_report.md'}")
        print("下一步：按 0–5 给每个分项打分（留空的会被当成 0 并提示），再运行本脚本不带 --seed-from-library。")
        return 0

    cfg = load_config(args.config)
    errors: list[str] = []
    warnings: list[str] = []
    enzyme_c, discovery_c, known_w, discovery_w, taxa_w, threshold = validate_weights(cfg, errors, warnings)
    if args.min_taxa_score is not None:
        threshold = args.min_taxa_score
    if errors:
        print("ranking config rejected:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    problems: list[str] = []
    enzyme_rows: list[dict[str, Any]] = []
    taxa_rows: list[dict[str, Any]] = []
    withheld: list[dict[str, str]] = []

    auto_scorer = None
    if args.auto_score:
        auto_scorer = AutoScorer(
            args.library, args.reference_enzymes, args.genomes, args.literature, args.disease
        )

    if args.enzymes is not None:
        if not args.enzymes.is_file():
            print(f"error: enzyme registry not found: {args.enzymes}", file=sys.stderr)
            return 2
        enzyme_rows = rank_enzymes(
            read_tsv(args.enzymes),
            enzyme_c,
            discovery_c,
            known_w,
            discovery_w,
            args.site,
            problems,
            auto_scorer,
            args.require_min_criteria,
            args.require_min_evidence,
            withheld,
        )

    if args.taxa is not None:
        if not args.taxa.is_file():
            print(f"error: taxa registry not found: {args.taxa}", file=sys.stderr)
            return 2
        taxa_rows = rank_taxa(
            read_tsv(args.taxa), taxa_w, threshold, args.site, problems, warnings, auto_scorer,
            args.require_min_criteria, args.require_min_evidence, withheld,
        )

    missing = [p for p in problems if "cannot be derived" in p]
    if missing and not args.allow_missing_scores:
        print(
            f"{len(missing)} score cell(s) are neither given nor derivable; nothing written.",
            file=sys.stderr,
        )
        for item in missing[:20]:
            print(f"- {item}", file=sys.stderr)
        if len(missing) > 20:
            print(f"- ... {len(missing) - 20} more", file=sys.stderr)
        breakable = {item.split("'")[1] for item in missing if "'" in item}
        hints = {key: DERIVABLE_FROM[key] for key in breakable if key in DERIVABLE_FROM}
        if hints:
            print("\nThese become derivable if you pass the matching source:", file=sys.stderr)
            for key, flag in sorted(hints.items()):
                print(f"  - {key}: {flag}", file=sys.stderr)
        print(
            "\nOtherwise fill them in the registry, or accept zeros with --allow-missing-scores "
            "(the gap is then recorded in score_sources and flagged in the report).",
            file=sys.stderr,
        )
        print("Scores that cannot be derived and must be judged by you:", file=sys.stderr)
        for key, explanation in MANUAL_ONLY.items():
            print(f"  - {key}: {explanation}", file=sys.stderr)
        return 1

    if not enzyme_rows and not taxa_rows:
        print(
            "nothing to rank: pass --enzymes and/or --taxa, or --seed-from-library to start from the library.",
            file=sys.stderr,
        )
        return 2

    if withheld:
        write_tsv(
            args.output / "withheld_rows.tsv",
            withheld,
            ["table", "id", "name", "reason", "priority_score"],
        )

    if enzyme_rows:
        write_tsv(args.output / "enzyme_priority_ranking.tsv", enzyme_rows, ENZYME_OUT_FIELDS)
        ranked_n = sum(1 for row in enzyme_rows if row["selection_status"] == "ranked")
        print(f"[enzyme] {ranked_n} of {len(enzyme_rows)} row(s) ranked -> {args.output / 'enzyme_priority_ranking.tsv'}")
        if ranked_n < len(enzyme_rows):
            print(f"[enzyme] {len(enzyme_rows) - ranked_n} withheld by the evidence gate; see withheld_rows.tsv",
                  file=sys.stderr)
        if ranked_n == 0:
            print(
                "warning: 没有一行满足证据门槛，enzyme ranking 里没有名次。"
                "这不是「没有候选」，而是「证据不足以排序」——补齐证据或放宽门槛。",
                file=sys.stderr,
            )
    if taxa_rows:
        write_tsv(args.output / "taxa_priority_ranking.tsv", taxa_rows, TAXA_OUT_FIELDS)
        selected = [row for row in taxa_rows if row["selection_status"] == "selected"]
        write_tsv(args.output / "selected_taxa.tsv", selected, TAXA_OUT_FIELDS)
        (args.output / "selected_taxa.txt").write_text(
            "".join(f"{row['genus']} {row['species']}".strip() + "\n" for row in selected),
            encoding="utf-8",
        )
        ranked_n = sum(1 for row in taxa_rows if row["selection_status"] in ("selected", "defer"))
        print(f"[taxa] {ranked_n} of {len(taxa_rows)} row(s) ranked; {len(selected)} selected -> {args.output}")
        if ranked_n < len(taxa_rows):
            print(f"[taxa] {len(taxa_rows) - ranked_n} withheld by the evidence gate; see withheld_rows.tsv",
                  file=sys.stderr)
        if ranked_n == 0:
            print(
                "warning: 没有一行满足证据门槛，ranking 里没有名次。"
                "这不是「没有候选」，而是「证据不足以排序」——补齐证据或放宽门槛。",
                file=sys.stderr,
            )

    report = render_report(
        enzyme_rows,
        taxa_rows,
        threshold,
        args.site,
        None,
        problems,
        warnings,
        auto_scorer.literature_used if auto_scorer else None,
        args.disease,
    )
    (args.output / "ranking_report.md").write_text(report, encoding="utf-8")
    print(f"wrote {args.output / 'ranking_report.md'}")
    if problems:
        print(f"note: {len(problems)} data problem(s); see the report", file=sys.stderr)
    if warnings:
        print(f"note: {len(warnings)} warning(s); see the report", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
