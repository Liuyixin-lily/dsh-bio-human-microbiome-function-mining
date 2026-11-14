#!/usr/bin/env python3
"""Turn plugin evidence into a work order a non-specialist can send to a vendor.

The plugin already produces `experimental_design.md`, but that document is written
for people who will run the bench work themselves. A user who says "我不是很懂分
子生物学，帮我写一份能直接发给公司做基因合成/表达/测活的方案" needs something
different:

- a **module split** the vendor can quote line by line;
- for every module: what we supply, what they deliver, and how we will accept it;
- the **exact sequences** in an appendix, copied verbatim (never invented);
- the **pre-registered decision rule** taken from the hypotheses table, so the
  conclusion is fixed before the data arrive;
- a **quick glossary** and a **"what I must confirm"** checklist, because the reader
  is not a molecular biologist;
- explicit **biosafety / IP / data** items that must be agreed in writing.

Two things this script deliberately never does:

- it never invents a price or a turnaround time. Those cells read `需询价` /
  `待确认` and are meant to be filled by the vendor's quote;
- it never invents a sequence. Sequences are copied from a FASTA the user already
  has; when there is no FASTA it writes a clearly-marked MISSING file instead of a
  plausible-looking placeholder.

Usage:

    python3 scripts/build_cro_work_order.py \
        --card outputs/task/target_function_card.json \
        --candidates outputs/task/summary/final_target_candidates.tsv \
        --hypotheses outputs/task/summary/experimental_hypotheses.tsv \
        --sequences outputs/task/candidate_sequences/candidate_proteins.faa \
        --outdir outputs/task/cro_package \
        --scope candidates --bsl BSL-1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCOPE_CHOICES = ("assay_first", "candidates", "full")
BSL_CHOICES = ("BSL-1", "BSL-2")
LANG_CHOICES = ("zh", "en")

MODULE_FIELDS = [
    "module_id",
    "module_zh",
    "module_en",
    "in_scope",
    "objective_zh",
    "inputs_from_us",
    "deliverables",
    "acceptance_criteria",
    "vendor_to_confirm",
    "price_status",
    "turnaround_days",
    "notes",
]

QUOTE_REQUIRED = "需询价 / quote required"
TAT_TBD = "待公司填写 / TBD"

# Modules are declared once. `scopes` says which module sets include them.
MODULES: list[dict[str, Any]] = [
    {
        "id": "M1",
        "zh": "基因合成与表达载体构建",
        "en": "Gene synthesis, codon optimization and cloning",
        "scopes": ("assay_first", "candidates", "full"),
        "objective": "按我们给出的氨基酸序列合成基因，优化密码子后克隆进可诱导表达载体，交付测序验证过的质粒与甘油菌。",
        "inputs": "附录 A 的氨基酸序列（逐字使用）；如需标签，请按附录 A 标注的位置与种类加上。",
        "deliverables": "全长测序无错的质粒 1 份（≥ 10 µg，附测序报告与图谱）；对应甘油菌 1 支；密码子优化后的核苷酸序列文件。",
        "acceptance": "全长测序与附录 A 的氨基酸序列翻译一致；无预期外的移码或终止子；质粒图谱与载体名称一致。",
        "confirm": "载体骨架与标签位置是否与我们的表达宿主匹配；是否允许我们指定载体。",
    },
    {
        "id": "M3",
        "zh": "小试重组表达与可溶性判定",
        "en": "Small-scale expression and solubility check",
        "scopes": ("assay_first", "candidates", "full"),
        "objective": "在常规大肠杆菌表达宿主中小试诱导，判定目标蛋白是可溶表达还是进入包涵体，为后续纯化路线提供依据。",
        "inputs": "M1 交付的质粒。",
        "deliverables": "诱导前后全菌与上清/沉淀的 SDS-PAGE 图；可溶性结论；建议的诱导条件（温度、诱导剂浓度、时长）。",
        "acceptance": "目标条带分子量与预期一致（±10%）；每份泳道都有上样量说明；明确写出可溶比例或“不可溶”的结论。",
        "confirm": "若不可溶，是否包含一轮条件优化，以及是否会产生额外费用。",
    },
    {
        "id": "M4",
        "zh": "放大表达与纯化",
        "en": "Scale-up expression and purification",
        "scopes": ("assay_first", "candidates", "full"),
        "objective": "放大培养并纯化出可用于体外酶活测定的重组蛋白。",
        "inputs": "M1 质粒；M3 的条件建议。",
        "deliverables": "纯化蛋白 ≥ 0.5 mg（浓度与体积实测值）；纯度 SDS-PAGE 图；缓冲液配方与保存条件；分装若干管。",
        "acceptance": "SDS-PAGE 主带纯度 ≥ 90%（光密度估算）；浓度以 A280 或 Bradford 实测并注明方法；缓冲液成分完整可复现。",
        "confirm": "标签是否保留（是否切除）、纯化是否含分子筛步骤、是否提供内毒素检测（若后续用于细胞实验）。",
    },
    {
        "id": "M5",
        "zh": "体外酶活方法建立（阳性对照）",
        "en": "In vitro assay development with a positive control",
        "scopes": ("assay_first", "candidates", "full"),
        "objective": "用已知具有该活性的酶建立并验证检测方法，先证明方法本身能work，再用于候选蛋白。",
        "inputs": "目标反应、底物与产物（目标卡片）；我们指定的阳性对照酶（若我们未提供序列，请在报价中注明是否有商品化产品及其来源）。",
        "deliverables": "方法描述（底物浓度、缓冲液、pH、温度、检测方式、标准曲线）；阳性对照的剂量-反应数据；背景与检出限。",
        "acceptance": "阳性对照信号随蛋白量单调上升；阴性/空白信号低于阳性最低点的 20%；给出至少 3 个独立重复。",
        "confirm": "是否需要我们提供底物；底物是否为非常规试剂（若需自行合成，请单独报价并说明周期）。",
    },
    {
        "id": "M6",
        "zh": "候选蛋白平行酶活测定",
        "en": "Parallel activity assay across candidates",
        "scopes": ("candidates", "full"),
        "objective": "在同一个已建立的方法下平行测定全部候选蛋白，使结果之间可比。",
        "inputs": "M4 交付的各候选蛋白；附表 B 的候选清单（编号、来源物种、筛选依据）。",
        "deliverables": "每个候选的比活（U/mg）或相对活性；每个候选至少 3 个独立重复的原始数据；逐候选的结论表。",
        "acceptance": "全部候选在同一批次、同一底物批次下测定；每个候选都有对应空载体对照；原始数据（色谱图/荧光读数）随报告交付。",
        "confirm": "候选数量较多时的分批策略与批次间校正方式。",
    },
    {
        "id": "M2",
        "zh": "催化残基突变体（阴性对照）",
        "en": "Catalytic-residue mutants as negative controls",
        "scopes": ("full",),
        "objective": "构建预测活性位点残基的突变体，作为“活性来自该蛋白本身而不是共纯化杂质”的关键阴性对照。",
        "inputs": "M1 质粒；我们提供的候选残基清单（若未提供，请先向我们确认，不要自行推测位点）。",
        "deliverables": "每个突变体的质粒与甘油菌；测序验证报告。",
        "acceptance": "突变位点经测序确认，且无其他意外突变；突变体蛋白表达量与野生型相当（SDS-PAGE 判定）。",
        "confirm": "突变体数量与是否需要同时提供野生型复测。",
    },
    {
        "id": "M7",
        "zh": "对照体系与排除实验",
        "en": "Controls and artefact exclusion",
        "scopes": ("assay_first", "candidates", "full"),
        "objective": "排除“活性来自宿主蛋白、培养基成分或底物自发水解”这三种最常见的假阳性来源。",
        "inputs": "M4 蛋白；空载体转化菌（同宿主同诱导条件）。",
        "deliverables": "空载体对照、热失活蛋白对照、无蛋白空白对照三组数据，与实验组同批测定。",
        "acceptance": "三种对照均显著低于实验组；若某对照与实验组无差异，报告须明确指出该候选不可判定。",
        "confirm": "热失活步骤是否在贵方常规流程内，若不在请单独报价。",
    },
    {
        "id": "M8",
        "zh": "扩展表征（底物谱、pH/温度曲线、动力学）",
        "en": "Extended characterization",
        "scopes": ("full",),
        "objective": "刻画酶的底物偏好与最适条件，用于判断它是否真能承担我们关心的生理反应。",
        "inputs": "M4 纯化蛋白；候选底物清单。",
        "deliverables": "底物谱（相对活性矩阵）；pH 与温度曲线；如可行，给出 Km / kcat。",
        "acceptance": "每个条件点有重复；曲线含拟合方法与拟合优度；底物谱须包含至少一个“不应被切开”的阴性底物。",
        "confirm": "非常规底物是否需要贵方合成或采购，及其对周期的影响。",
    },
    {
        "id": "M9",
        "zh": "细胞或菌株水平验证（可选，需专门 CRO）",
        "en": "Cell or strain-level validation (needs a specialist CRO)",
        "scopes": ("full",),
        "objective": "验证该酶在更接近生理的条件下是否真的产生目标产物。",
        "inputs": "M1 质粒；宿主菌株或细胞模型（由我们指定）。",
        "deliverables": "敲除/回补或异源表达菌株的构建报告；目标产物的定量检测结果。",
        "acceptance": "构建经测序或 PCR 验证；产物定量有标准品校准；有野生型与空载对照。",
        "confirm": "贵方是否承接该物种/细胞的操作；若否，请只报 M1–M8 并说明。",
    },
    {
        "id": "M10",
        "zh": "数据交付、生物安全与知识产权",
        "en": "Data delivery, biosafety and IP",
        "scopes": ("assay_first", "candidates", "full"),
        "objective": "把交付形式、数据归属、生物安全责任与保密条款在开工前写清楚，避免后期争议。",
        "inputs": "本工作单；双方的保密协议。",
        "deliverables": "结题报告（含方法、原始数据、结论）；原始数据电子件；未用样品的处理说明。",
        "acceptance": "报告可直接引用（含方法与仪器型号）；原始数据可追溯；样品处理方式书面确认。",
        "confirm": "数据与成果归属、是否允许我们发表、保密期限、剩余样品返还或销毁方式。",
    },
]

GLOSSARY_ZH = [
    ("基因合成", "不用从生物体里取基因，直接按氨基酸序列化学合成一段对应的 DNA。"),
    ("密码子优化", "同一个氨基酸可以由不同的 DNA 三联体编码，按表达宿主的偏好改写，让蛋白更容易被生产出来。"),
    ("表达载体", "一个环状 DNA，用来把基因带进细胞并让它被读成蛋白。"),
    ("转化 / 甘油菌", "把质粒送进细菌的过程叫转化；把成功转化的菌冻在甘油里保存，就是甘油菌。"),
    ("诱导表达", "用化学信号（如 IPTG）让细胞开始大量生产我们想要的蛋白。"),
    ("可溶 / 包涵体", "蛋白正确折叠、留在细胞液里叫可溶；折叠错误、聚成团块叫包涵体，需要额外变性复性。"),
    ("亲和纯化", "给蛋白接一个“把手”（如 His 标签），用只抓这个把手的材料把它从杂蛋白里拉出来。"),
    ("SDS-PAGE", "按分子量把蛋白分开的凝胶电泳，用来判断目标蛋白有没有、纯不纯。"),
    ("比活（U/mg）", "每毫克蛋白每分钟转化多少底物，是酶活性的标准化指标。"),
    ("阳性对照", "用一个已知有这个活性的酶走同一套流程，证明方法本身没问题。"),
    ("阴性对照", "用一个应该没有活性的样品（空载体、突变体、加热失活的蛋白）走同一套流程，排除假阳性。"),
    ("Km / kcat", "Km 反映酶对底物的亲和力，kcat 反映单个酶分子每秒能处理多少底物。"),
    ("BSL-1 / BSL-2", "生物安全等级。常规实验室大肠杆菌属 BSL-1；涉及致病菌活菌操作通常需要 BSL-2。"),
]


def read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def read_tsv(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.is_file():
        return []
    import csv  # noqa: PLC0415

    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_fasta(path: Path | None) -> list[tuple[str, str]]:
    if path is None or not path.is_file():
        return []
    records: list[tuple[str, str]] = []
    header: str | None = None
    chunks: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(">"):
            if header is not None:
                records.append((header, "".join(chunks)))
            header = line[1:].strip()
            chunks = []
        elif line.strip():
            chunks.append(line.strip())
    if header is not None:
        records.append((header, "".join(chunks)))
    return records


def modules_for_scope(scope: str) -> list[dict[str, Any]]:
    selected = [m for m in MODULES if scope in m["scopes"]]
    return sorted(selected, key=lambda m: int(m["id"].lstrip("M")))


def card_fields(card: dict[str, Any]) -> dict[str, str]:
    return {
        "target_id": card.get("target_id", "") or "(未提供)",
        "enzyme_name": card.get("enzyme_name", "") or "(未提供)",
        "ec": card.get("ec", "") or "(无 EC 号)",
        "reaction": card.get("reaction", "") or "(未提供)",
        "substrate": card.get("substrate", "") or "(未提供)",
        "product": card.get("product", "") or "(未提供)",
        "cofactor": card.get("cofactor", "") or "(无)",
        "fold": card.get("structural_fold", "") or "(未提供)",
        "notes": card.get("notes", ""),
        "input_source": card.get("input_source", "") or "manual",
        "library_id": card.get("library_id", ""),
    }


def candidate_rows(
    candidates: list[dict[str, str]],
    limit: int | None,
    fasta: list[tuple[str, str]] | None = None,
) -> list[dict[str, str]]:
    rows = []
    for row in candidates:
        accession = row.get("protein_accession", "")
        has_seq = match_sequence(fasta or [], accession) is not None
        rows.append(
            {
                "rank": row.get("final_rank", "") or row.get("overall_rank", ""),
                "accession": accession,
                "organism": row.get("organism_or_strain", ""),
                "evidence": row.get("evidence_base", "") or row.get("validation_status", ""),
                "ec": row.get("fedkea_ec", ""),
                "tm": row.get("tm_score_mean", ""),
                "sequence_status": "有序列 / available" if has_seq else "缺序列 / MISSING",
            }
        )
    if limit is not None:
        rows = rows[:limit]
    return rows


def match_sequence(records: list[tuple[str, str]], accession: str) -> tuple[str, str] | None:
    if not accession:
        return None
    for header, seq in records:
        token = header.split("|")[0].split()[0]
        if token == accession or accession in header.split():
            return header, seq
    for header, seq in records:
        if accession in header:
            return header, seq
    return None


def fmt_cell(value: str) -> str:
    return value.replace("\t", " ").replace("\n", " ").strip()


def write_modules_tsv(path: Path, modules: list[dict[str, Any]]) -> None:
    import csv  # noqa: PLC0415

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MODULE_FIELDS, delimiter="\t")
        writer.writeheader()
        for module in modules:
            writer.writerow(
                {
                    "module_id": module["id"],
                    "module_zh": fmt_cell(module["zh"]),
                    "module_en": fmt_cell(module["en"]),
                    "in_scope": "yes",
                    "objective_zh": fmt_cell(module["objective"]),
                    "inputs_from_us": fmt_cell(module["inputs"]),
                    "deliverables": fmt_cell(module["deliverables"]),
                    "acceptance_criteria": fmt_cell(module["acceptance"]),
                    "vendor_to_confirm": fmt_cell(module["confirm"]),
                    "price_status": QUOTE_REQUIRED,
                    "turnaround_days": TAT_TBD,
                    "notes": "",
                }
            )


def render_markdown(
    card: dict[str, str],
    candidates: list[dict[str, str]],
    hypotheses: list[dict[str, str]],
    modules: list[dict[str, Any]],
    scope: str,
    bsl: str,
    sequences_available: bool,
    n_sequences: int,
    context_blocks: list[tuple[str, str]] | None = None,
) -> str:
    scope_text = {
        "assay_first": "只做“把检测方法建起来”这一段（阳性对照酶合成 → 表达纯化 → 方法验证），先确认方法可行，再谈候选。",
        "candidates": "主路径：候选蛋白合成 → 表达纯化 → 同一方法平行测活，用于验证筛选结论。",
        "full": "全路径：在主路径之外，加催化残基突变体、对照排除、底物谱/动力学，以及（可选的）细胞或菌株水平验证。",
    }[scope]

    lines: list[str] = []
    lines.append("# 委托实验工作单 / Contract Research Work Order")
    lines.append("")
    lines.append("> 这份文件是给**承接实验的公司/CRO**看的。它由插件根据已有证据自动生成，")
    lines.append("> 其中**所有价格与周期都留空**（标注为“需询价 / 待公司填写”），必须由承接方报价。")
    lines.append("> 任何我们没给出的事实，文件里都会写成“未提供”，而不是替我们猜一个。")
    lines.append("")
    lines.append("## 0. 这份单子怎么用（给不熟悉分子生物学的使用者）")
    lines.append("")
    lines.append("1. 发给公司的是三份：本文件、`cro_modules.tsv`（可报价的模块表）、`cro_sequences.faa`（逐字序列）。")
    lines.append("   第四份 `cro_gap_list.md` 是给你自己看的——先把里面的项清掉，再发出。")
    lines.append("2. 公司会按模块编号逐条报价；你可以只买其中几段，不必整包买。")
    lines.append("3. 在发出之前，先读完第 7 节「你必须先确认的事」——那一节里的项目如果没填，公司无法开工。")
    lines.append("4. 第 6 节是**先定好的判定规则**：数据回来之前就定好什么算成功，避免事后解释。")
    lines.append("5. 第 8 节是术语表，每个词一句话解释，不需要任何分子生物学背景。")
    lines.append("")
    lines.append("## 1. 项目目标")
    lines.append("")
    lines.append(f"- 目标编号：`{card['target_id']}`")
    lines.append(f"- 目标酶：{card['enzyme_name']}")
    lines.append(f"- EC 号：{card['ec']}")
    lines.append(f"- 反应：{card['reaction']}")
    lines.append(f"- 底物 → 产物：{card['substrate']} → {card['product']}")
    lines.append(f"- 辅因子：{card['cofactor']}")
    lines.append(f"- 折叠提示：{card['fold']}")
    if card["library_id"]:
        lines.append(f"- 目标来源：内置目标库条目 `{card['library_id']}`")
    lines.append("")
    lines.append(f"**本次委托范围（`--scope {scope}`）**：{scope_text}")
    lines.append("")
    lines.append("我们要回答的问题只有一句：**在这个目标上，哪些候选蛋白真的具备该酶活性？**")
    lines.append("判定依据见第 6 节，不依赖主观判断。")
    lines.append("")
    lines.append("## 2. 模块总览（可逐条报价）")
    lines.append("")
    lines.append("| 模块 | 名称 | 我方提供 | 交付物 | 验收标准 | 报价 | 周期 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for m in modules:
        lines.append(
            f"| {m['id']} | {m['zh']} / {m['en']} | {m['inputs']} | {m['deliverables']} | "
            f"{m['acceptance']} | {QUOTE_REQUIRED} | {TAT_TBD} |"
        )
    lines.append("")
    lines.append("完整字段（含“需贵方确认项”）见 `cro_modules.tsv`。")
    lines.append("")
    lines.append("## 3. 候选蛋白清单")
    lines.append("")
    if candidates:
        lines.append("| 序号 | 蛋白登录号 | 来源物种 | 筛选依据 | FedKEA EC | TM-score | 序列 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for c in candidates:
            lines.append(
                f"| {c['rank']} | {c['accession']} | {c['organism']} | {c['evidence']} | "
                f"{c['ec'] or '—'} | {c['tm'] or '—'} | {c.get('sequence_status', '—')} |"
            )
        with_seq = sum(1 for c in candidates if c.get("sequence_status", "").startswith("有序列"))
        lines.append("")
        lines.append(
            f"共 {len(candidates)} 个候选，其中 {with_seq} 个有可用序列。"
            "每个候选都要走同一批模块，结果才可比。"
        )
        if with_seq < len(candidates):
            lines.append("")
            lines.append(
                "**标为「缺序列」的候选，公司无法为其合成基因**。请先补序列，"
                "或者本次只提交有序列的那些，并在报告里注明其余候选暂缓。"
            )
    else:
        lines.append("**尚未提供候选清单。** 这通常意味着筛选还没跑完，或者这份方案是提前准备的。")
        lines.append("")
        lines.append("如果现在还没有候选，建议先只买 `assay_first` 范围：先把检测方法用阳性对照酶建起来。")
        lines.append("等候选确定后，再用同一份工作单加买 M6（平行测活）。这样不会因为等筛选而卡住。")
    lines.append("")
    lines.append("## 4. 序列附录")
    lines.append("")
    if sequences_available:
        lines.append(f"逐字序列见 `cro_sequences.faa`（{n_sequences} 条）。")
        lines.append("")
        lines.append("**请公司严格按附录序列合成，不要自行改动**；如需优化密码子，请只改核苷酸、不改氨基酸，")
        lines.append("并在交付时提供优化后的核苷酸序列以便我们核对翻译结果。")
    else:
        lines.append("**本次没有可提供的序列文件。** 我们没有用任何占位序列来凑数——见 `cro_sequences.MISSING.md`。")
        lines.append("")
        lines.append("在这个状态下，公司只能报 M5（方法建立）与流程性模块的价格，M1（基因合成）无法报价。")
    lines.append("")
    lines.append("## 5. 我们要求的三类对照（M7）")
    lines.append("")
    lines.append("1. **空载体对照**：只有载体、没有我们的基因，走完全相同的诱导与纯化流程。")
    lines.append("2. **热失活对照**：纯化好的蛋白加热失活后同法测定。")
    lines.append("3. **无蛋白空白**：只有缓冲液与底物。")
    lines.append("")
    lines.append("这三种对照任何一项与实验组无差异，该候选的结论必须写成“不可判定”，而不是“阴性”。")
    lines.append("")
    lines.append("## 6. 数据回来之前就先定好的判定规则")
    lines.append("")
    if hypotheses:
        lines.append(
            "只列出**本次委托范围内的候选**。未纳入本次委托的候选不在此表，"
            "以免让承接方对不在订单内的蛋白执行判定规则。"
        )
        lines.append("")
        lines.append("| 候选 | 假设 | 证伪条件（出现即判定该假设不成立） |")
        lines.append("| --- | --- | --- |")
        for h in hypotheses:
            cand = h.get("protein_accession", "") or h.get("candidate_id", "")
            stmt = h.get("hypothesis_statement", "")
            fals = h.get("falsification_criteria", "")
            lines.append(f"| {cand} | {stmt} | {fals} |")
        lines.append("")
        lines.append("判定规则来自 `experimental_hypotheses.tsv`，是**预先注册**的：先在数据之前写下什么算成功，")
        lines.append("再看数据。这样即使结果不理想，也不能事后更改标准。")
    else:
        lines.append("尚未提供 `experimental_hypotheses.tsv`，因此这里只有通用判定框架（请务必补上）：")
        lines.append("")
        lines.append("- **成立**：候选蛋白的活性显著高于三类对照（建议 ≥ 3 倍空载体背景），且有阳性对照同批验证方法有效。")
        lines.append("- **不成立**：无可重复活性，或活性可追溯到共纯化杂质、底物自发水解。")
        lines.append("- **不可判定**：蛋白不溶、表达量不足、对照失效——此时结论是“这次实验没做成”，不是“这个蛋白没功能”。")
        lines.append("")
        lines.append("这三条要在发出工作单之前确认，并写进与公司的沟通记录。")
    lines.append("")
    lines.append("## 7. 你必须先确认的事")
    lines.append("")
    lines.append("| 项目 | 说明 | 状态 |")
    lines.append("| --- | --- | --- |")
    lines.append(f"| 生物安全等级 | 本单按 `{bsl}` 准备；若涉及致病菌活菌操作，须由你所在单位的生物安全委员会确认等级与条件 | 待确认 |")
    lines.append("| 基因来源合法性 | 合成基因是否涉及第三方专利或材料转移协议（MTA） | 待确认 |")
    lines.append("| 序列 | 附录 A/B 是否完整；缺序列时 M1 无法开工 | 待确认 |")
    lines.append("| 底物可得性 | 目标底物是否常规商品；非常规底物可能需单独合成并显著延长周期 | 待确认 |")
    lines.append("| 预算与时限 | 本单不含任何价格与周期，请以公司报价为准 | 待确认 |")
    lines.append("| 数据与成果归属 | 是否可发表、原始数据归属、保密期限 | 待确认 |")
    lines.append("| 剩余样品处理 | 返还、留存还是销毁 | 待确认 |")
    lines.append("")
    lines.append("**关于生物安全**：以上只是你需要逐项确认的清单，不构成合规结论。")
    lines.append("合成基因的序列筛查通常由合成公司在接单时执行；我们不对其流程作任何假设。")
    lines.append("")
    lines.append("## 8. 术语表（不需要分子生物学背景）")
    lines.append("")
    lines.append("| 术语 | 一句话解释 |")
    lines.append("| --- | --- |")
    for term, explain in GLOSSARY_ZH:
        lines.append(f"| {term} | {explain} |")
    lines.append("")
    lines.append("## 9. 报价时需要公司回答的问题")
    lines.append("")
    for q in [
        "报价是否包含基因合成、亚克隆、全长测序？测序失败如何处理？",
        "表达载体能否由我们指定？标签种类与位置能否指定？是否提供去标签版本？",
        "可溶性失败时，是否包含一轮条件优化？重做与退款条款是什么？",
        "纯化是否包含分子筛？是否提供内毒素检测（若后续做细胞实验）？",
        "非常规底物能否代购或代合成？对周期与价格的影响？",
        "交付形态是什么：质粒 / 甘油菌 / 纯蛋白 / 原始数据？",
        "原始数据（测序峰图、色谱图、质谱图）是否随报告交付？",
        "本单各模块的最短周期与并行可能性？",
    ]:
        lines.append(f"- {q}")
    lines.append("")
    if context_blocks:
        lines.append("## 附录 A：我方提供的背景与风险材料")
        lines.append("")
        lines.append(
            "以下内容由委托方提供，用于说明**已知的不确定性**，帮助承接方判断该不该接、"
            "以及实验设计要注意什么。它是委托方自己的陈述与文献判断，未经承接方核验，"
            "也不构成对任何蛋白功能的结论。"
        )
        lines.append("")
        for name, text in context_blocks:
            lines.append(f"### 来源：`{name}`")
            lines.append("")
            lines.append(text.rstrip())
            lines.append("")

    lines.append("## 10. 边界声明")
    lines.append("")
    lines.append("- 本文件由插件依据已有证据生成，**不是**实验结果，也不构成任何功能结论。")
    lines.append("- 文件中没有价格、周期、货号或供应商名称；这些必须来自承接方报价。")
    lines.append("- 文件中没有占位序列；序列只来自我们实际提供的 FASTA。")
    lines.append("- 在实验完成并独立重复之前，任何候选都不能被写成“已证实具有该功能”。")
    lines.append("")
    return "\n".join(lines)


def render_gap_list(
    card: dict[str, str], candidates: list[dict[str, str]], sequences_available: bool, bsl: str
) -> str:
    gaps: list[str] = []
    if card["target_id"] == "(未提供)":
        gaps.append("目标卡片缺失或为空：没有目标就无法定义“要证明什么”。先跑 build-target-function-card。")
    if card["ec"] == "(无 EC 号)":
        gaps.append("目标没有 EC 号：这不影响实验，但公司报价时可能需要一个“酶名”描述，请用目标酶名沟通。")
    if card["substrate"] == "(未提供)":
        gaps.append("未提供底物：M5/M8 无法报价，因为检测方法依赖底物。")
    if not candidates:
        gaps.append("没有候选蛋白清单：M1/M6 无法报价。只能先买 assay_first 范围。")
    if not sequences_available:
        gaps.append("没有可交付的序列：M1（基因合成）无法开工。需要候选蛋白 FASTA。")
    gaps.append(f"生物安全等级目前按 {bsl} 预填，必须由你所在机构确认后才能对外发出。")
    gaps.append("本工作单没有任何价格与周期，发出前请确认你接受“以公司报价为准”。")
    lines = ["# 发出前必须补齐的项 / Gaps before sending", ""]
    lines.append("下面每一项没解决，对应模块就无法开工。不要把这些项当成可选项。")
    lines.append("")
    for i, gap in enumerate(gaps, 1):
        lines.append(f"{i}. {gap}")
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a vendor-facing contract-research work order from plugin evidence.",
    )
    parser.add_argument("--card", type=Path, default=None, help="target_function_card.json")
    parser.add_argument("--candidates", type=Path, default=None, help="final_target_candidates.tsv or a scored candidates table")
    parser.add_argument("--hypotheses", type=Path, default=None, help="experimental_hypotheses.tsv")
    parser.add_argument("--sequences", type=Path, default=None, help="candidate protein FASTA to copy verbatim")
    parser.add_argument("--outdir", type=Path, required=True, help="Output directory for the CRO package")
    parser.add_argument("--scope", choices=SCOPE_CHOICES, default="candidates", help="Which module set to include")
    parser.add_argument("--bsl", choices=BSL_CHOICES, default="BSL-1", help="Biosafety level to prefill (must be confirmed by the user's institution)")
    parser.add_argument("--max-candidates", type=int, default=None, help="Only include the first N candidates")
    parser.add_argument("--lang", choices=LANG_CHOICES, default="zh", help="Document language (zh default)")
    parser.add_argument(
        "--context",
        type=Path,
        action="append",
        default=None,
        help="Markdown file with caveats/risk notes we provide to the vendor (repeatable). Included verbatim as an appendix.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    card = card_fields(read_json(args.card))
    fasta = read_fasta(args.sequences)
    candidates = candidate_rows(read_tsv(args.candidates), args.max_candidates, fasta)
    hypotheses = read_tsv(args.hypotheses)

    # A vendor must not be asked to run decision rules for proteins that are not in
    # the order. Keep only hypotheses whose accession is part of this package.
    excluded_hypotheses = 0
    if candidates and hypotheses:
        ordered = {c["accession"] for c in candidates if c["accession"]}
        kept = []
        for row in hypotheses:
            key = (row.get("protein_accession") or row.get("candidate_id") or "").strip()
            if key in ordered:
                kept.append(row)
            else:
                excluded_hypotheses += 1
        hypotheses = kept

    args.outdir.mkdir(parents=True, exist_ok=True)
    modules = modules_for_scope(args.scope)

    context_blocks: list[tuple[str, str]] = []
    for path in args.context or []:
        if not path.is_file():
            print(f"error: --context file not found: {path}", file=sys.stderr)
            return 2
        text = path.read_text(encoding="utf-8")
        if len(text.splitlines()) > 300:
            print(
                f"warning: {path} has {len(text.splitlines())} lines; a very long appendix "
                "may bury the quotable module table",
                file=sys.stderr,
            )
        context_blocks.append((path.name, text))

    # sequences: copy verbatim, matched by accession; never synthesise a placeholder
    written = 0
    missing: list[str] = []
    seq_lines: list[str] = []
    for candidate in candidates:
        hit = match_sequence(fasta, candidate["accession"])
        if hit is None:
            missing.append(candidate["accession"] or "(无登录号)")
            continue
        header, seq = hit
        seq_lines.append(
            f">{candidate['accession']}|{candidate['organism']}|module=M1|source=plugin_candidate_sequences"
        )
        seq_lines.append(f"; original_header={header}")
        for i in range(0, len(seq), 60):
            seq_lines.append(seq[i : i + 60])
        written += 1
    # if there is no candidate list, copy whatever FASTA was given, labelled as target/reference
    if not candidates and fasta:
        for header, seq in fasta:
            seq_lines.append(f">UNASSIGNED|{header}|module=M1|source=plugin_candidate_sequences")
            for i in range(0, len(seq), 60):
                seq_lines.append(seq[i : i + 60])
            written += 1

    seq_path = args.outdir / "cro_sequences.faa"
    if written:
        seq_path.write_text("\n".join(seq_lines) + "\n", encoding="utf-8")
    else:
        (args.outdir / "cro_sequences.MISSING.md").write_text(
            "# 缺少序列 / No sequences available\n\n"
            "本次没有生成 `cro_sequences.faa`，因为没有可用的候选蛋白 FASTA。\n\n"
            "这个脚本不会生成占位序列：一段看起来像真序列的假序列一旦被公司拿去合成，\n"
            "会导致整批实验白做。请先跑序列提取，例如：\n\n"
            "```bash\n"
            "python3 scripts/extract_candidate_sequences.py --help\n"
            "```\n\n"
            "拿到 `candidate_proteins.faa` 后重新运行本脚本并加 `--sequences <该文件>`。\n",
            encoding="utf-8",
        )

    write_modules_tsv(args.outdir / "cro_modules.tsv", modules)

    if excluded_hypotheses:
        print(
            f"note: {excluded_hypotheses} hypothesis row(s) excluded because those candidates "
            "are not in this order",
            file=sys.stderr,
        )

    md = render_markdown(
        card,
        candidates,
        hypotheses,
        modules,
        args.scope,
        args.bsl,
        sequences_available=written > 0,
        n_sequences=written,
        context_blocks=context_blocks,
    )
    md_path = args.outdir / "cro_work_order.md"
    md_path.write_text(md, encoding="utf-8")

    gap_path = args.outdir / "cro_gap_list.md"
    gap_path.write_text(
        render_gap_list(card, candidates, written > 0, args.bsl), encoding="utf-8"
    )

    print(f"wrote {md_path}")
    print(f"wrote {args.outdir / 'cro_modules.tsv'} ({len(modules)} modules)")
    print(f"wrote {gap_path}")
    if written:
        print(f"wrote {seq_path} ({written} sequence(s) copied verbatim)")
    else:
        print(f"wrote {args.outdir / 'cro_sequences.MISSING.md'} (no sequences available)")
    if missing:
        print("warning: no sequence found for candidate(s): " + ", ".join(missing), file=sys.stderr)
    if context_blocks:
        print(f"附上 {len(context_blocks)} 份背景/风险材料（逐字引用，注明来源）")
    print("提醒：价格与周期一律留空，须由承接方报价；本文件不含任何功能结论。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
