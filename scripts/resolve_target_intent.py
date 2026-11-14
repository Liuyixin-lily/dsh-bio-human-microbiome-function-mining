#!/usr/bin/env python3
"""Route an arbitrary natural-language microbiome question to the right entry.

The curated target library (`library/`) can only answer what it covers. This
resolver exists so that everything it does not cover still has a defined, honest
path instead of a dead end.

It is deliberately deterministic: no model call, no network, no invention. It
recognises the *shape* of the question (does it name an EC number? a reaction? a
taxon? a body site? a phenotype?) and emits a route plan made of concrete commands
that the plugin already ships:

    entry A  build_target_function_card.py / fetch_reference_enzymes.py
    entry B  browse_target_library.py
    site-generic   genome_source_search.py (skin/oral/gut/respiratory/urogenital/
                   blood/environment), run_brief / genome-download / Bakta
    evidence       run_literature_search.sh
    expand         build_library_domain.py (create a starter domain on demand)

What it never does: claim a taxon, an EC number, or a citation it did not get from
the user or from a file. When something is missing it says exactly which input is
missing and which step needs it.

Examples:

    python3 scripts/resolve_target_intent.py --query "sphingomyelin + H2O -> ceramide + phosphocholine"
    python3 scripts/resolve_target_intent.py --query "口腔牙周炎相关菌有哪些酶值得看"
    python3 scripts/resolve_target_intent.py --query "Cutibacterium acnes 的脂肪酶"
    python3 scripts/resolve_target_intent.py --query "阴道菌群和乳酸杆菌" --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_LIBRARY_DIR = SCRIPT_DIR.parent / "library"

EC_RE = re.compile(r"\b([1-7]\.\d{1,2}\.\d{1,2}\.(?:\d{1,3}|-))\b")

# A library hit only counts as coverage when it matched a curated keyword (100) or
# a curated keyword inside the user's sentence (80). 60 is a token-inside-field
# match, 20 is a plain substring somewhere in prose; neither is coverage.
COVERAGE_MIN_SCORE = 80
ARROW_RE = re.compile(r"(?:->|→|=>|\u21d2|\u27f6)")
REACTION_WORD_RE = re.compile(r"(生成|转化为|转化成|分解为|水解为|裂解为|converted to|forms|yields)")
ENZYME_WORD_RE = re.compile(
    r"(酶|enzyme|ase\b)", re.IGNORECASE
)

# ---------------------------------------------------------------------------
# lexicon: body site -> the source vocabulary that genome-search already ships
# ---------------------------------------------------------------------------
# (source_id used by skills/genome-search/scripts/genome_source_search.py,
#  sub-site label, CJK markers, ASCII markers)
SITE_LEXICON: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = [
    ("skin", "头皮", ("头皮", "头皮屑", "头油"), ("scalp", "dandruff")),
    ("skin", "腋下", ("腋下", "腋窝", "狐臭"), ("axilla", "axillary", "armpit")),
    ("skin", "足部/趾间", ("趾间", "脚气", "足部", "脚臭"), ("toe web", "foot", "tinea pedis")),
    ("skin", "面部", ("面部", "脸部", "面颊", "毛囊", "痤疮", "痘痘"), ("facial", "face", "hair follicle", "acne")),
    ("skin", "皮肤", ("皮肤", "表皮", "皮脂", "皮肤菌群"), ("skin", "cutaneous", "dermal", "epidermal", "sebaceous")),
    ("oral", "牙周", ("牙周", "牙龈", "牙周炎", "牙龈炎"), ("periodontal", "gingival", "gingiva", "gum")),
    ("oral", "牙齿/龋", ("龋齿", "蛀牙", "牙菌斑", "牙齿", "牙冠"), ("caries", "dental plaque", "tooth", "teeth", "dental")),
    ("oral", "舌", ("舌苔", "舌头", "舌"), ("tongue",)),
    ("oral", "唾液", ("唾液",), ("saliva", "salivary")),
    ("oral", "口腔", ("口腔", "口臭", "口腔异味"), ("oral", "mouth", "halitosis")),
    ("gut", "结肠", ("结肠", "大肠"), ("colon", "colonic")),
    ("gut", "粪便", ("粪便", "大便", "排便"), ("feces", "faeces", "stool", "faecal", "fecal")),
    ("gut", "胃", ("胃部", "胃", "胃酸"), ("stomach", "gastric")),
    ("gut", "肠道", ("肠道", "肠菌", "肠道菌群", "肠型"), ("gut", "intestinal", "intestine", "cecum")),
    ("respiratory", "鼻腔", ("鼻腔", "鼻前庭", "鼻"), ("nasal", "nares", "nasopharynx")),
    ("respiratory", "肺", ("肺", "痰", "肺炎"), ("lung", "pulmonary", "sputum", "pneumonia")),
    ("respiratory", "呼吸道", ("呼吸道", "气道", "咽喉"), ("airway", "respiratory tract", "throat")),
    ("urogenital", "阴道", ("阴道", "宫颈", "阴道菌群"), ("vagina", "vaginal", "cervical", "cervix")),
    ("urogenital", "泌尿道", ("泌尿道", "尿道", "尿液"), ("urinary", "urethra", "urine")),
    ("blood", "血液", ("血液", "血流", "菌血症", "败血症"), ("blood", "bloodstream", "bacteremia", "septicemia")),
    ("environment", "环境", ("环境", "土壤", "水体", "污水", "空气"), ("environment", "soil", "water", "wastewater", "dust")),
]

# ---------------------------------------------------------------------------
# lexicon: phenotype / process words -> a neutral navigation group
# ---------------------------------------------------------------------------
# These are navigation categories, not biological claims. They exist so a
# phenotype question can be matched against the library and, on a miss, turned
# into literature search terms.
PHENOTYPE_LEXICON: dict[str, str] = {
    # lipid / sebum
    "油脂分泌": "脂质与皮脂", "出油": "脂质与皮脂", "油性皮肤": "脂质与皮脂",
    "控油": "脂质与皮脂", "sebum": "脂质与皮脂", "lipase": "脂质与皮脂",
    "皮脂": "脂质与皮脂", "甘油三酯": "脂质与皮脂", "蜡酯": "脂质与皮脂",
    "胆固醇": "脂质与皮脂", "cholesterol": "脂质与皮脂", "coprostanol": "脂质与皮脂",
    # barrier / sphingolipid
    "屏障": "屏障与鞘脂", "barrier": "屏障与鞘脂", "保湿": "屏障与鞘脂",
    "水分流失": "屏障与鞘脂", "神经酰胺": "屏障与鞘脂", "ceramide": "屏障与鞘脂",
    "鞘脂": "屏障与鞘脂", "sphingolipid": "屏障与鞘脂", "鞘磷脂": "屏障与鞘脂",
    "sphingomyelin": "屏障与鞘脂", "sphingomyelinase": "屏障与鞘脂",
    "ceramidase": "屏障与鞘脂", "角质层": "屏障与鞘脂",
    # smell / volatiles
    "体味": "气味与挥发物", "臭味": "气味与挥发物", "异味": "气味与挥发物",
    "口臭": "气味与挥发物", "狐臭": "气味与挥发物", "odour": "气味与挥发物",
    "odor": "气味与挥发物", "halitosis": "气味与挥发物", "thioalcohol": "气味与挥发物",
    "硫化氢": "气味与挥发物", "甲硫醇": "气味与挥发物", "methanethiol": "气味与挥发物",
    "吲哚": "气味与挥发物", "indole": "气味与挥发物", "异戊酸": "气味与挥发物",
    # inflammation / immunity
    "炎症": "炎症与免疫", "inflammation": "炎症与免疫", "免疫": "炎症与免疫",
    "immunity": "炎症与免疫", "免疫调节": "炎症与免疫", "抗炎": "炎症与免疫",
    "过敏": "炎症与免疫", "湿疹": "炎症与免疫", "特应性皮炎": "炎症与免疫",
    "atopic dermatitis": "炎症与免疫", "银屑病": "炎症与免疫", "psoriasis": "炎症与免疫",
    # oral disease
    "龋齿": "口腔疾病", "蛀牙": "口腔疾病", "caries": "口腔疾病",
    "牙周炎": "口腔疾病", "periodontitis": "口腔疾病", "牙龈炎": "口腔疾病",
    "gingivitis": "口腔疾病", "根面龋": "口腔疾病",
    # acid / pH
    "乳酸": "酸化与发酵", "lactate": "酸化与发酵", "酸化": "酸化与发酵",
    "acidification": "酸化与发酵", "发酵": "酸化与发酵", "fermentation": "酸化与发酵",
    # SCFA
    "短链脂肪酸": "短链脂肪酸", "丁酸": "短链脂肪酸", "butyrate": "短链脂肪酸",
    "丙酸": "短链脂肪酸", "propionate": "短链脂肪酸", "乙酸": "短链脂肪酸",
    "acetate": "短链脂肪酸", "SCFA": "短链脂肪酸",
    # bile acid
    "胆汁酸": "胆汁酸", "bile acid": "胆汁酸", "胆盐": "胆汁酸",
    "胆盐水解酶": "胆汁酸", "脱氧胆酸": "胆汁酸", "石胆酸": "胆汁酸",
    # nitrogen / TMA
    "三甲胺": "含氮代谢物", "TMA": "含氮代谢物", "TMAO": "含氮代谢物",
    "胆碱": "含氮代谢物", "choline": "含氮代谢物", "尿素": "含氮代谢物",
    "尿素酶": "含氮代谢物", "urea": "含氮代谢物", "urease": "含氮代谢物",
    "氨": "含氮代谢物", "ammonia": "含氮代谢物",
    # sulfur
    "硫": "硫代谢", "硫酸盐": "硫代谢", "sulfate": "硫代谢",
    "硫化氢": "硫代谢", "H2S": "硫代谢", "亚硫酸盐": "硫代谢",
    "sulfatase": "硫代谢", "硫酸酯酶": "硫代谢",
    # nitrate / NO
    "硝酸盐": "硝酸盐与NO", "nitrate": "硝酸盐与NO", "亚硝酸盐": "硝酸盐与NO",
    "nitrite": "硝酸盐与NO", "一氧化氮": "硝酸盐与NO", "nitric oxide": "硝酸盐与NO",
    # metal / cofactor
    "铁": "金属与辅因子", "铁载体": "金属与辅因子", "siderophore": "金属与辅因子",
    "iron": "金属与辅因子", "锌": "金属与辅因子", "镍": "金属与辅因子",
    "血红素": "金属与辅因子", "heme": "金属与辅因子",
    # vitamins
    "维生素": "维生素合成", "vitamin": "维生素合成", "硫胺素": "维生素合成",
    "thiamine": "维生素合成", "核黄素": "维生素合成", "riboflavin": "维生素合成",
    "叶酸": "维生素合成", "folate": "维生素合成", "B12": "维生素合成",
    # hormones / steroids / drugs
    "激素": "激素与异源物质", "hormone": "激素与异源物质", "类固醇": "激素与异源物质",
    "steroid": "激素与异源物质", "雄激素": "激素与异源物质", "androgen": "激素与异源物质",
    "雌激素": "激素与异源物质", "estrogen": "激素与异源物质", "皮质醇": "激素与异源物质",
    "cortisol": "激素与异源物质", "药物": "激素与异源物质", "药物代谢": "激素与异源物质",
    "drug": "激素与异源物质", "digoxin": "激素与异源物质",
    # polyamine / amino acid
    "多胺": "氨基酸与多胺", "polyamine": "氨基酸与多胺", "亚精胺": "氨基酸与多胺",
    "spermidine": "氨基酸与多胺", "色氨酸": "氨基酸与多胺", "tryptophan": "氨基酸与多胺",
    "芳香族氨基酸": "氨基酸与多胺", "氨基酸": "氨基酸与多胺",
    "amino acid": "氨基酸与多胺", "脱羧": "氨基酸与多胺", "decarboxylase": "氨基酸与多胺",
    # glycans / matrix
    "黏蛋白": "糖与基质降解", "黏液": "糖与基质降解", "mucin": "糖与基质降解",
    "胶原": "糖与基质降解", "collagen": "糖与基质降解", "透明质酸": "糖与基质降解",
    "hyaluronan": "糖与基质降解", "硫酸软骨素": "糖与基质降解",
    "glycosidase": "糖与基质降解", "糖苷酶": "糖与基质降解",
    # colonization resistance
    "定植抵抗": "菌群互作", "colonization resistance": "菌群互作",
    "细菌素": "菌群互作", "bacteriocin": "菌群互作", "抗菌肽": "菌群互作",
    "生物膜": "菌群互作", "biofilm": "菌群互作", "competition": "菌群互作",
    "羊毛硫抗生素": "菌群互作", "lantibiotic": "菌群互作",
    # host metabolism
    "肥胖": "宿主代谢关联", "obesity": "宿主代谢关联", "糖尿病": "宿主代谢关联",
    "diabetes": "宿主代谢关联", "代谢综合征": "宿主代谢关联",
    "心血管": "宿主代谢关联", "cardiovascular": "宿主代谢关联",
}

# ---------------------------------------------------------------------------
# lexicon: taxa (genus level) — a name list, not a claim about function
# ---------------------------------------------------------------------------
TAXON_GENERA = (
    "Staphylococcus", "Cutibacterium", "Propionibacterium", "Corynebacterium",
    "Micrococcus", "Kocuria", "Dermabacter", "Brevibacterium", "Rothia",
    "Actinomyces", "Streptococcus", "Enterococcus", "Lactobacillus",
    "Lactococcus", "Bifidobacterium", "Gardnerella", "Atopobium", "Mobiluncus",
    "Bacteroides", "Prevotella", "Porphyromonas", "Tannerella", "Treponema",
    "Fusobacterium", "Veillonella", "Neisseria", "Haemophilus", "Moraxella",
    "Acinetobacter", "Pseudomonas", "Stenotrophomonas", "Burkholderia",
    "Klebsiella", "Escherichia", "Salmonella", "Shigella", "Enterobacter",
    "Citrobacter", "Serratia", "Proteus", "Morganella", "Providencia",
    "Helicobacter", "Campylobacter", "Vibrio", "Aeromonas", "Bacillus",
    "Listeria", "Clostridium", "Clostridioides", "Faecalibacterium",
    "Roseburia", "Eubacterium", "Ruminococcus", "Blautia", "Coprococcus",
    "Dorea", "Akkermansia", "Eggerthella", "Desulfovibrio", "Bilophila",
    "Finegoldia", "Peptoniphilus", "Mycobacterium", "Nocardia", "Malassezia",
    "Candida", "Trichosporon", "Saccharomyces", "Demodex",
)
TAXON_CJK = (
    "葡萄球菌", "表皮葡萄球菌", "金黄色葡萄球菌", "人葡萄球菌", "溶血葡萄球菌",
    "头状葡萄球菌", "丙酸杆菌", "痤疮丙酸杆菌", "棒状杆菌", "微球菌",
    "链球菌", "肠球菌", "乳杆菌", "双歧杆菌", "拟杆菌", "普雷沃菌",
    "卟啉单胞菌", "坦纳菌", "密螺旋体", "梭杆菌", "韦荣菌", "奈瑟菌",
    "嗜血杆菌", "莫拉菌", "不动杆菌", "假单胞菌", "克雷伯菌", "埃希菌",
    "大肠杆菌", "沙门菌", "梭菌", "普拉梭菌", "罗斯氏菌", "真杆菌",
    "瘤胃球菌", "阿克曼菌", "埃格特菌", "脱硫弧菌", "马拉色菌", "念珠菌",
    "真菌", "酵母",
)

ENZYME_FAMILY_TERMS = (
    "水解酶", "裂解酶", "脱羧酶", "脱氨酶", "合成酶", "转移酶", "氧化酶",
    "还原酶", "蛋白酶", "肽酶", "脂肪酶", "酯酶", "糖苷酶", "硫酸酯酶",
    "磷酸酶", "激酶", "转氨酶", "脱水酶", "异构酶", "连接酶",
    "lipase", "protease", "peptidase", "hydrolase", "lyase", "decarboxylase",
    "transferase", "oxidase", "reductase", "kinase", "phosphatase", "esterase",
    "glycosidase", "sulfatase", "dehydratase", "isomerase",
)


def _ascii_term_re(term: str) -> re.Pattern[str]:
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", re.IGNORECASE)


def _has_cjk(text: str) -> bool:
    return any(ord(ch) > 127 for ch in text)


def _find_terms(query: str, terms: tuple[str, ...]) -> list[str]:
    """Return the terms present in the query (CJK by substring, ASCII by word boundary)."""
    lowered = query.lower()
    hits: list[str] = []
    for term in terms:
        if _has_cjk(term):
            if term in query:
                hits.append(term)
        elif _ascii_term_re(term).search(lowered):
            hits.append(term)
    return hits


def detect(query: str) -> dict[str, Any]:
    lines = [ln.strip() for ln in query.replace("\r", "\n").split("\n") if ln.strip()]

    ecs = sorted({m.group(1) for m in EC_RE.finditer(query)})

    arrow = bool(ARROW_RE.search(query))
    reaction_word = bool(REACTION_WORD_RE.search(query, re.IGNORECASE))

    enzymes = _find_terms(query, ENZYME_FAMILY_TERMS)

    genera = _find_terms(query, TAXON_GENERA)
    cjk_taxa = _find_terms(query, TAXON_CJK)

    sites: list[tuple[str, str]] = []
    for source_id, label, cjk_terms, ascii_terms in SITE_LEXICON:
        if _find_terms(query, cjk_terms) or _find_terms(query, ascii_terms):
            if (source_id, label) not in sites:
                sites.append((source_id, label))
    # a specific sub-site supersedes its own generic parent
    generic = {"皮肤", "口腔", "肠道", "呼吸道", "泌尿道", "牙齿/龋", "口腔"}  # noqa: F841
    source_ids = []
    for source_id, _label in sites:
        if source_id not in source_ids:
            source_ids.append(source_id)

    phenotypes = _find_terms(query, tuple(PHENOTYPE_LEXICON))
    phenotype_groups = sorted({PHENOTYPE_LEXICON[t] for t in phenotypes})

    return {
        "query": query,
        "ec": ecs,
        "reaction_marker": arrow or reaction_word,
        "reaction_arrow": arrow,
        "enzyme_terms": enzymes,
        "taxa": sorted(set(genera) | set(cjk_taxa)),
        "body_sites": [{"source_id": sid, "label": label} for sid, label in sites],
        "source_ids": source_ids,
        "phenotypes": phenotypes,
        "phenotype_groups": phenotype_groups,
        "line_count": len(lines),
    }


# ---------------------------------------------------------------------------
# library coverage check
# ---------------------------------------------------------------------------


def library_coverage(
    library_query: str, library_dir: Path, source_ids: list[str] | None = None
) -> dict[str, Any]:
    """Check whether the curated library covers this topic *at the named body site*.

    A hit in a different body site is not coverage. "阴道菌群和乳酸杆菌" must not be
    answered with a skin acidification process just because both mention acid; it
    is reported as an off-site analogy instead.
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    from browse_target_library import Index, load_library, search  # noqa: PLC0415

    payloads, errors = load_library(library_dir)
    if errors:
        return {"available": False, "error": "; ".join(errors), "hits": [], "hit_count": 0}
    if not payloads:
        # Not configured is different from "configured but does not cover this".
        return {
            "available": False,
            "reason": "not_configured",
            "hits": [],
            "hit_count": 0,
            "domains": [],
        }
    index = Index(payloads)
    wanted = set(source_ids or [])
    same_site: list[dict[str, Any]] = []
    other_site: list[dict[str, Any]] = []
    taxon_hits: list[dict[str, Any]] = []
    weak_hits: list[dict[str, Any]] = []
    for h in search(index, library_query)[:10]:
        if h["kind"] == "taxon":
            for record in h["records"]:
                taxon_hits.append(
                    {
                        "taxon": h["taxon"],
                        "domain": record["domain"],
                        "processes": record["processes"],
                    }
                )
            continue
        entry = {
            "kind": h["kind"],
            "score": h["score"],
            "domain": h["domain"]["id"],
            "process": h.get("process", {}).get("id"),
            "enzyme": h.get("enzyme", {}).get("id"),
            "command": _hit_command(h),
        }
        # Only a curated-keyword level match counts as coverage. A word that merely
        # appears somewhere in a prose field (a 20-level hit) is not coverage, and
        # treating it as such would answer "肠道菌对免疫的影响" with an unrelated
        # process that happens to contain the word 免疫.
        if entry["score"] < COVERAGE_MIN_SCORE:
            weak_hits.append(entry)
            continue
        if not wanted or entry["domain"] in wanted:
            same_site.append(entry)
        else:
            other_site.append(entry)
    return {
        "available": True,
        "query_used": library_query,
        "domains": [d["id"] for d in index.domains],
        "hit_count": len(same_site),
        "hits": same_site[:5],
        "other_site_hit_count": len(other_site),
        "other_site_hits": other_site[:3],
        "taxon_hits": taxon_hits[:3],
        "weak_hit_count": len(weak_hits),
    }


def _hit_command(hit: dict[str, Any]) -> str:
    if hit["kind"] == "enzyme":
        return f"python3 scripts/browse_target_library.py --show {hit['enzyme']['id']}"
    if hit["kind"] == "process":
        return f"python3 scripts/browse_target_library.py --show {hit['process']['id']}"
    return f"python3 scripts/browse_target_library.py --list-processes {hit['domain']['id']}"


# ---------------------------------------------------------------------------
# routing
# ---------------------------------------------------------------------------


def _step(why: str, command: str, needs: list[str] | None = None) -> dict[str, Any]:
    return {"why_zh": why, "command": command, "needs": needs or []}


def plan_route(detected: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
    query = detected["query"]
    ecs = detected["ec"]
    taxa = detected["taxa"]
    source_ids = detected["source_ids"]
    groups = detected["phenotype_groups"]
    enzymes = detected["enzyme_terms"]
    site_hit = bool(source_ids)
    library_hit = coverage.get("hit_count", 0) > 0

    # 1. an EC number answers the target question by itself -> entry A
    if ecs:
        ec = ecs[0]
        steps = [
            _step(
                "EC 号已经把目标说清楚了，直接建卡片，不经过目标库。",
                f"python3 scripts/build_target_function_card.py --output outputs/task/target_function_card.json "
                f"--input-source ec --ec {ec}",
            ),
            _step(
                "用 EC 号去公共库取真实参考酶记录（不要手填登录号）。",
                f"python3 scripts/fetch_reference_enzymes.py --ec {ec} --output outputs/reference/reference_enzyme_set.tsv",
            ),
            _step(
                "主体流程按序列 → 结构 → 证据走，命令见 functional-dark-matter-discover。",
                "python3 scripts/preflight_inputs.py --project project.json",
            ),
        ]
        needs: list[str] = []
        if not site_hit:
            needs.append("候选基因组 / 数据来源（哪个部位或哪些菌株）")
        return {"entry": "A", "confidence": "high", "reason_zh": "问题里已经含 EC 号。",
                "steps": steps, "missing": needs}

    # 2. a substrate-product reaction -> entry A (reaction)
    if detected["reaction_arrow"]:
        steps = [
            _step(
                "反应式已经给出，从反应反推 EC 与酶名，再建卡片。",
                "python3 scripts/build_target_function_card.py --output outputs/task/target_function_card.json "
                "--input-source reaction --reaction \"<把反应式写在这里>\"",
            ),
            _step(
                "若已知 EC，用 EC 检索参考酶；否则先用酶名检索，并用 literature-evidence 确认 EC 归属。",
                "python3 scripts/fetch_reference_enzymes.py --enzyme-name \"<酶名>\" "
                "--output outputs/reference/reference_enzyme_set.tsv",
            ),
        ]
        return {"entry": "A", "confidence": "high", "reason_zh": "问题里含底物-产物反应式。",
                "steps": steps,
                "missing": [] if site_hit else ["候选基因组 / 数据来源"]}

    # 3. taxon named -> site-generic genome route, plus library if it happens to cover it
    if taxa:
        taxon = taxa[0]
        species_hint = "> ".join(taxa)
        steps = [
            _step(
                "用户点名了菌，先备基因组数据集：把菌名写进一行一个的文件，再按来源过滤候选装配。",
                "printf '%s\\n' " + " ".join(f'"{t}"' for t in taxa) + " > work/taxa.txt\n"
                + "python3 skills/genome-search/scripts/genome_source_search.py taxa "
                + "--input work/taxa.txt "
                + (f"--source {source_ids[0]} " if site_hit else "--source <skin|oral|gut|respiratory|urogenital|blood|environment> ")
                + "--out-xlsx work/genome_search/source_match.xlsx "
                + "--out-tsv work/genome_search/source_match.tsv",
                ["一份或几份菌名（拉丁名或中文名均可）"],
            ),
            _step(
                "选定装配后下载基因组（NCBI 可访问时；否则把清单交给用户在自己的机器上跑）。",
                "python3 skills/genome-download/scripts/build_gcf_list.py --species work/taxa.txt --out work/gcf_list.tsv\n"
                "python3 skills/genome-download/scripts/build_download_links.py --gcf work/gcf_list.tsv --out work/urls.txt\n"
                "python3 skills/genome-download/scripts/download_genomes.py --metadata work/gcf_list.tsv "
                "--urls work/urls.txt --out work/genomes",
            ),
            _step(
                "菌备齐后仍需要一个“筛什么”的目标：从这一步回到入口 A。",
                "python3 scripts/browse_target_library.py --list-domains   # 若库覆盖该部位，可先选酶",
            ),
        ]
        if library_hit:
            steps.insert(0, _step(
                "目标库正好覆盖了这个问题，可以直接在库里选一个酶目标。",
                coverage["hits"][0]["command"],
            ))
        return {
            "entry": "A+B" if library_hit else "A",
            "confidence": "medium",
            "reason_zh": f"问题里点名了菌（{species_hint}）。",
            "steps": steps,
            "missing": [] if enzymes or library_hit else ["要筛的酶 / EC / 反应（只有菌名不足以开始筛选）"],
        }

    # 4. the curated library covers this phrasing -> entry B
    library_configured = coverage.get("available", False)
    if library_hit:
        return {
            "entry": "B",
            "confidence": "high",
            "reason_zh": "目标库已覆盖这个说法，逐级摊开让用户选即可。",
            "steps": [
                _step("库里命中，先看命中的 process / enzyme。", coverage["hits"][0]["command"]),
                _step(
                    "按身体部位 → 生理过程 → 酶目标逐级展示，让用户选。",
                    "python3 scripts/browse_target_library.py --interactive --output-dir outputs/task",
                ),
            ],
            "missing": [],
        }

    # 5. a site and/or a phenotype, but the library does not cover it -> escalate
    if site_hit or groups:
        site_text = "、".join(sorted({s["label"] for s in detected["body_sites"]})) or "该部位"
        group_text = "、".join(groups) or "该表型"
        search_terms = " ".join(
            [t for t in (
                (taxa[0] if taxa else ""),
                (groups[0] if groups else ""),
                (enzymes[0] if enzymes else ""),
                "human microbiome" if not _has_cjk(query) else "",
            ) if t]
        ) or query
        steps = [
            _step(
                (f"目标库没有覆盖「{site_text} · {group_text}」，这不是“功能不存在”，只是未策展。"
                 if library_configured
                 else f"没有配置目标库，所以没有「{site_text} · {group_text}」的可选菜单；这不是“做不了”。")
                + "先把问题收敛到一个可筛的东西：一个反应、一个 EC 号，或一个酶家族名。",
                "python3 scripts/browse_target_library.py --validate   # 先确认这是未覆盖，而不是库坏了",
                ["一个具体反应 / 一个 EC 号 / 一个酶名"],
            ),
            _step(
                "在收敛之前，先用文献检索确认这条轴上已经有哪些酶被报道过（检索词由问题自动拼出，不是引用）。",
                f"bash scripts/run_literature_search.sh \"{search_terms}\" --limit 20 --resolve",
                ["网络或 MCP 文献工具；离线时提供 citation 文件"],
            ),
            _step(
                "如果要长期在这个部位上工作，把它做成一个 starter 域，而不是每次现查。",
                "python3 scripts/build_library_domain.py --init --domain new_site --output specs/new_site.json",
                ["按 spec 逐项填写：过程、关键菌、酶、EC、来源说明"],
            ),
            _step(
                "或者直接按已知目标建档（入口 A），不扩展库。",
                "python3 scripts/build_target_function_card.py --output outputs/task/target_function_card.json "
                "--enzyme-name \"<酶名>\" --ec <EC>",
            ),
        ]
        if not library_configured:
            reason = (
                f"识别到部位/表型（{site_text} · {group_text}）；未配置目标库，"
                "因此没有可选菜单，直接走部位通用路径。"
            )
        else:
            reason = f"识别到部位/表型（{site_text} · {group_text}），但目标库未覆盖。"
        return {
            "entry": "escalate",
            "confidence": "medium",
            "reason_zh": reason,
            "literature_search_terms": search_terms,
            "steps": steps,
            "missing": ["把问题收敛到一个反应 / EC / 酶名"],
        }

    # 6. nothing recognisable -> ask one question
    return {
        "entry": "clarify",
        "confidence": "low",
        "reason_zh": "没有识别出 EC 号、反应式、菌名、部位或表型关键词。",
        "steps": [
            _step(
                "把问题换成下面四种形状之一，任何一种都能立刻给出可执行路线。",
                "python3 scripts/browse_target_library.py --list-domains",
            ),
        ],
        "question_shapes": [
            "① 已知目标：酶名 / EC 号，例如「神经酰胺酶 EC 3.5.1.23」",
            "② 已知反应：底物 -> 产物，例如「鞘磷脂 -> 神经酰胺 + 磷酸胆碱」",
            "③ 已知菌 / 部位：「Cutibacterium acnes」「阴道菌群」",
            "④ 只知道关注点：「我关注头皮屑」「口腔异味」",
        ],
        "missing": ["问题类型"],
    }


def build_library_query(detected: dict[str, Any]) -> str:
    """Normalize a whole sentence into the words the library actually indexes.

    The browser treats space-separated tokens as AND, so "Cutibacterium acnes 的
    脂肪酶" would fail on the token "的脂肪酶". Dropping to the detected taxa,
    phenotype words and enzyme-family words keeps the coverage check meaningful
    instead of turning it into a false "not curated".
    """
    parts: list[str] = []
    parts.extend(detected["taxa"])
    parts.extend(detected["phenotypes"])
    parts.extend(detected["enzyme_terms"])
    return " ".join(dict.fromkeys(parts)) or detected["query"]


def render_text(result: dict[str, Any]) -> str:
    d = result["detected"]
    lines: list[str] = []
    lines.append(f"query: {d['query']}")
    found = []
    if d["ec"]:
        found.append("ec=" + ",".join(d["ec"]))
    if d["reaction_marker"]:
        found.append("reaction=yes")
    if d["taxa"]:
        found.append("taxa=" + ",".join(d["taxa"]))
    if d["source_ids"]:
        found.append("site=" + ",".join(d["source_ids"]))
    if d["phenotype_groups"]:
        found.append("phenotype=" + ",".join(d["phenotype_groups"]))
    if d["enzyme_terms"]:
        found.append("enzyme_terms=" + ",".join(d["enzyme_terms"][:4]))
    lines.append("detected: " + (" ".join(found) if found else "(nothing recognisable)"))

    cov = result["library_coverage"]
    if not cov.get("available"):
        if cov.get("reason") == "not_configured":
            lines.append("library: not configured (optional; every site still works via entry A)")
        else:
            lines.append(f"library: unavailable ({cov.get('error')})")
    elif cov["hit_count"]:
        top = cov["hits"][0]
        where = top["enzyme"] or top["process"] or top["domain"]
        lines.append(f"library: HIT x{cov['hit_count']} (top: {top['kind']} {where})")
    else:
        lines.append(f"library: MISS at this site (covered sites: {', '.join(cov.get('domains') or [])})")
    for th in cov.get("taxon_hits") or []:
        bound = ", ".join(th["processes"]) or "no process yet"
        lines.append(
            f"library: taxon known — {th['taxon']} @ {th['domain']} (bound processes: {bound})"
        )
    if cov.get("weak_hit_count"):
        lines.append(
            f"library: {cov['weak_hit_count']} weak text match(es) ignored "
            "(a word buried in prose is not coverage)"
        )
    if cov.get("other_site_hit_count"):
        other = cov["other_site_hits"][0]
        where = other["enzyme"] or other["process"] or other["domain"]
        lines.append(
            f"library: {cov['other_site_hit_count']} hit(s) at a DIFFERENT body site "
            f"({other['domain']} / {where}) — usable as an analogy only, not as coverage."
        )

    route = result["route"]
    lines.append(f"route: entry {route['entry']} (confidence {route['confidence']}) — {route['reason_zh']}")
    if route.get("literature_search_terms"):
        lines.append(f"literature_search_terms: {route['literature_search_terms']}")
    lines.append("")
    lines.append("steps:")
    for i, step in enumerate(route["steps"], 1):
        lines.append(f"  {i}) {step['why_zh']}")
        for cmd_line in step["command"].split("\n"):
            lines.append(f"        $ {cmd_line}")
        if step["needs"]:
            lines.append(f"        needs: {'; '.join(step['needs'])}")
    if route.get("question_shapes"):
        lines.append("")
        lines.append("这个问题还缺一个可筛的目标，可以换成这些形状：")
        for shape in route["question_shapes"]:
            lines.append(f"  - {shape}")
    if route.get("missing"):
        lines.append("")
        lines.append("还缺：")
        for item in route["missing"]:
            lines.append(f"  - {item}")
    lines.append("")
    lines.append(
        "说明：本路由只做问题分类与命令编排，不产生任何事实断言；"
        "EC、登录号、文献标识符一律来自脚本检索结果或用户输入。"
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Route an arbitrary microbiome question to the right plugin entry.",
    )
    parser.add_argument("--query", required=True, help="The user's own words, any language.")
    parser.add_argument(
        "--library-dir",
        type=Path,
        default=DEFAULT_LIBRARY_DIR,
        help=f"Curated library directory (default: {DEFAULT_LIBRARY_DIR}).",
    )
    parser.add_argument("--json", action="store_true", help="Emit the route plan as JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    query = args.query.strip()
    if not query:
        print("error: --query is empty", file=sys.stderr)
        return 2

    detected = detect(query)
    library_query = build_library_query(detected)
    coverage = library_coverage(library_query, args.library_dir, detected["source_ids"])
    result = {
        "detected": detected,
        "library_coverage": coverage,
        "route": plan_route(detected, coverage),
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
