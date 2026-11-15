#!/usr/bin/env python3
"""Generate final candidate summaries from a scored candidate table.

Reads `scored_candidates_full.tsv`, optional `candidate_gene_evidence.tsv`, and
an optional project JSON that records `candidate_sequences.candidates` source
genome paths. Writes two deterministic artifacts:

- high_confidence_candidate_summary.tsv: every scored row with a short
  human-readable validation status and a machine-readable verdict.
- final_target_candidates.tsv: only the priority rules configured by
  --final-rules, defaulting to `USALIGN_TARGET_EC,SEQUENCE_ANNOTATION_CONFIRMED`.
- experimental_hypotheses.tsv: one explict falsifiable hypothesis per scored
  candidate, with mechanistic model, testable prediction, critical
  experiments, falsification criteria, ambient/alternative hypothesis,
  evidence chain, and optional literature citations.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from decisions import gate as decision_gate  # noqa: E402
from typing import Any


SUMMARY_FIELDS = [
    "overall_rank",
    "protein_accession",
    "organism_or_strain",
    "evidence_base",
    "tm_score_mean",
    "structural_score",
    "deer_distance",
    "deer_rank",
    "source_annotation",
    "gene_metadata",
    "fedkea_ec",
    "fedkea_confidence",
    "validation_status",
    "verdict",
]

FINAL_FIELDS = [
    "final_rank",
    "protein_accession",
    "organism_or_strain",
    # the alignment evidence itself, so a reader can see what the candidate was compared against
    "representative_id",
    "pident",
    "query_coverage",
    "evalue",
    "evidence_base",
    "tm_score_mean",
    "structural_score",
    "source_annotation",
    "locus_tag",
    "location",
    "fedkea_ec",
    "fedkea_confidence",
    "fedkea_accepted_name",
    "fedkea_other_names",
    "validation_status",
    "protein_fasta",
    "cds_fasta",
    "gene_fasta",
    "gene_source",
    "signalp_prediction",
    "is_secreted",
    "mature_protein_fasta",
]

HYPOTHESIS_FIELDS = [
    "overall_rank",
    "protein_accession",
    "organism_or_strain",
    "candidate_id",
    "target_context",
    "hypothesis_statement",
    "mechanistic_model",
    "testable_prediction",
    "critical_experiments",
    "falsification_criteria",
    "ambient_hypothesis",
    "evidence_chain",
    "literature_citations",
    "designer_notes",
    "provenance",
]


def read_tsv(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not path.is_file():
        return rows
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle, delimiter="\t") if row and any(row.values())]
    return rows


def load_candidate_paths(project_path: str | None) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """Return candidate metadata and genome metadata from a project JSON."""
    candidates: dict[str, dict[str, str]] = {}
    genomes: dict[str, dict[str, str]] = {}
    if not project_path:
        return candidates, genomes
    project = json.loads(Path(project_path).read_text(encoding="utf-8"))
    cs = project.get("candidate_sequences") or {}
    genomes = {name: dict(info) for name, info in (cs.get("genomes") or {}).items()}
    for accession, info in (cs.get("candidates") or {}).items():
        candidates[accession.strip()] = dict(info)
    return candidates, genomes


def evidence_base(row: dict[str, str]) -> str:
    rule = row.get("priority_rule", row.get("priority_tier", ""))
    if rule == "SEQUENCE_ANNOTATION_CONFIRMED":
        return "sequence+annotation"
    if row.get("deer_distance", "").strip() or row.get("deer_rank", "").strip():
        return "DEER"
    if row.get("structural_score", "").strip() or row.get("tm_score_mean", "").strip():
        return "US-align"
    if row.get("sequence_score", "").strip():
        return "sequence"
    return "annotation"


def validation_status(row: dict[str, str]) -> str:
    rule = row.get("priority_rule", row.get("priority_tier", ""))
    if rule == "SEQUENCE_ANNOTATION_CONFIRMED":
        return "high-confidence: DIAMOND sequence hit with matching existing source annotation; structure screening skipped"
    if rule == "USALIGN_TARGET_EC":
        return "high-confidence: US-align near-native + FedKEA target EC " + row.get("fedkea_final_result", "")
    if rule == "DEER_FEDKEA_CONFIRMED":
        return "medium: DEER fallback candidate confirmed as enzyme by FedKEA"
    if rule == "USALIGN_OTHER_EC":
        return (
            "medium: US-align near-native; FedKEA predicts EC "
            + row.get("fedkea_final_result", "")
            + " instead of the target EC - retained as a candidate for experimental testing, not excluded"
        )
    if rule == "USALIGN_NOT_ENZYME":
        return "low: US-align evidence but FedKEA predicts not an enzyme"
    if rule == "USALIGN_UNVALIDATED":
        return "medium: US-align near-native but no FedKEA validation yet"
    if rule == "DEER_FALLBACK":
        prob = row.get("fedkea_enzyme_probability", "").strip()
        if row.get("fedkea_is_enzyme", "").strip().lower() in ("false", "0", "no", ""):
            extra = " and FedKEA predicts not an enzyme" + (f", probability {prob}" if prob else "")
        elif prob:
            extra = f"; FedKEA probability {prob}"
        else:
            extra = ""
        return "low: DEER-only candidate" + extra
    if rule == "SEQUENCE_ONLY":
        return "sequence-only candidate; no structural validation"
    return "annotation-only candidate; no screening evidence"


def verdict(row: dict[str, str]) -> str:
    rule = row.get("priority_rule", row.get("priority_tier", ""))
    if rule == "SEQUENCE_ANNOTATION_CONFIRMED":
        return "high:sequence+annotation"
    if rule == "USALIGN_TARGET_EC":
        return "high:US-align+target_EC"
    if rule == "DEER_FEDKEA_CONFIRMED":
        return "medium:deer_fedkea_enzyme"
    if rule == "USALIGN_OTHER_EC":
        return "medium:US-align+non_target_EC"
    if rule == "USALIGN_NOT_ENZYME":
        return "low:US-align+not_enzyme"
    if rule == "USALIGN_UNVALIDATED":
        return "medium:US-align+unvalidated"
    if rule == "DEER_FALLBACK":
        return "low:deer_only"
    if rule == "SEQUENCE_ONLY":
        return "low:sequence_only"
    return "low:annotation_only"


def fetch_source_annotation(row: dict[str, str]) -> str:
    for key in ("annotation", "source_description", "existing_annotation"):
        value = (row.get(key) or "").strip()
        if value:
            return value
    return ""


def target_context(project: dict[str, Any]) -> str:
    card = project_card(project)
    pieces = []
    if card.get("enzyme_name"):
        pieces.append(card["enzyme_name"])
    if card.get("ec"):
        pieces.append(f"EC {card['ec']}")
    if card.get("reaction"):
        pieces.append(f"reaction: {card['reaction']}")
    elif card.get("substrate") and card.get("product"):
        pieces.append(f"{card['substrate']} -> {card['product']}")
    return " | ".join(pieces)


def hypothesis_statement(row: dict[str, str], project: dict[str, Any], target: str) -> str:
    acc = row.get("protein_accession") or row.get("candidate_id") or ""
    organism = row.get("organism_or_strain") or ""
    rule = row.get("priority_rule", row.get("priority_tier", ""))
    if rule == "SEQUENCE_ANNOTATION_CONFIRMED":
        basis = "strong DIAMOND sequence similarity and existing source annotation matching the target function"
    elif rule == "USALIGN_TARGET_EC":
        basis = "high structural similarity to the reference enzyme and FedKEA-predicted target EC"
    elif rule == "USALIGN_OTHER_EC":
        basis = "high structural similarity to the reference enzyme, although FedKEA predicts a different EC"
    elif rule == "USALIGN_NOT_ENZYME":
        basis = "high structural similarity to the reference enzyme but FedKEA predicts no enzyme activity"
    elif rule == "DEER_FEDKEA_CONFIRMED":
        basis = "DEER fallback activity and FedKEA-predicted enzyme activity"
    elif rule == "DEER_FALLBACK":
        basis = "DEER fallback structural resemblance without independent functional validation"
    elif rule == "SEQUENCE_ONLY":
        basis = "DIAMOND sequence similarity without resolved structural validation"
    else:
        basis = "source genome annotation alone"
    target_short = card_summary(project) or "the requested human-microbiome metabolic function"
    return (
        f"{organism} encodes the candidate protein {acc} that carries out {target_short}, "
        f"supported by {basis}."
    )


def card_summary(project: dict[str, Any]) -> str:
    card = project_card(project)
    if card.get("enzyme_name"):
        return card["enzyme_name"]
    if card.get("ec"):
        return f"the EC {card['ec']} enzyme"
    if card.get("reaction"):
        return f"the {card['reaction']} reaction"
    return ""


def mechanistic_model(row: dict[str, str], project: dict[str, Any]) -> str:
    source = fetch_source_annotation(row)
    rule = row.get("priority_rule", row.get("priority_tier", ""))
    model = "The protein is a divergent homolog of the target enzyme family."
    if source:
        model += f" The source annotation describes it as: {source}."
    if rule in ("USALIGN_TARGET_EC", "USALIGN_OTHER_EC", "DEER_FEDKEA_CONFIRMED"):
        model += " Structural and/or functional prediction support an enzyme active site that can accommodate the target substrate."
    elif rule == "SEQUENCE_ANNOTATION_CONFIRMED":
        model += " Existing functional annotation and sequence similarity together support enzyme activity; structural validation was not required."
    elif rule == "SEQUENCE_ONLY":
        model += " Sequence similarity supports an evolutionary relationship, but the active site geometry is unverified."
    return model


def testable_prediction(row: dict[str, str], target_ec: str = "") -> str:
    rule = row.get("priority_rule", row.get("priority_tier", ""))
    if rule in ("SEQUENCE_ANNOTATION_CONFIRMED", "USALIGN_TARGET_EC"):
        return "Purified recombinant protein will catalyze the target reaction in vitro with detectable substrate depletion and product formation."
    if rule == "USALIGN_OTHER_EC":
        predicted = (row.get("fedkea_final_result", "") or "").strip()
        target = (target_ec or row.get("target_ec", "") or "").strip()
        parts = ["Purified recombinant protein will show enzyme activity in vitro"]
        if predicted:
            parts.append(f"and is expected to catalyse the FedKEA-predicted EC {predicted} reaction")
        if target and predicted and target != predicted:
            parts.append(
                f"the decisive test is a side-by-side assay of the target EC {target} reaction and the "
                f"predicted EC {predicted} reaction: shared fold does not mean shared function, and the "
                "prediction does not settle it"
            )
        return "; ".join(parts) + "."
    if rule == "DEER_FEDKEA_CONFIRMED":
        return "Purified recombinant protein will show enzyme activity in vitro; the EC assignment will be reconciled by substrate/product assays."
    if rule == "SEQUENCE_ONLY":
        return "Purified recombinant protein will fold into the predicted structure and will either support the target reaction or bind the target substrate."
    if rule in ("USALIGN_UNVALIDATED", "DEER_FALLBACK"):
        return "Purified recombinant protein will show measurable activity in at least one compatible enzyme assay when tested under the conditions specified in the study."
    return "Purified recombinant protein will show no catalytic activity specific to the target reaction in the primary assay."


def critical_experiments(row: dict[str, str]) -> str:
    acc = row.get("protein_accession") or row.get("candidate_id") or ""
    parts = [
        f"Heterologous expression: clone and express {acc} in E. coli, purify the recombinant protein, and run an in vitro target-substrate assay with product detection controls.",
        "Knockout/complement: delete or knock down the native gene in the source organism and show loss of the predicted phenotype, then restore activity with a complementation construct.",
        "Specificity controls: include a catalytically dead mutant or unrelated enzyme as a negative control and a characterized ortholog as a positive control.",
    ]
    return "\n".join(parts)


def falsification_criteria(row: dict[str, str]) -> str:
    rule = row.get("priority_rule", row.get("priority_tier", ""))
    if rule == "SEQUENCE_ANNOTATION_CONFIRMED":
        return "No substrate conversion above the negative-control limit after at least three biological replicates, or the existing annotation fails to reproduce in the source organism, would falsify the hypothesis."
    if rule == "USALIGN_TARGET_EC":
        return "No substrate conversion above the negative-control limit after at least three biological replicates, or a catalytically dead mutant retains full activity, would falsify the hypothesis."
    if rule in ("DEER_FEDKEA_CONFIRMED", "USALIGN_OTHER_EC"):
        return "No enzyme activity in the primary assay and no alternative substrate conversion in orthogonal assays would lower priority and require reinterpretation of the structural/functional evidence."
    if rule == "SEQUENCE_ONLY":
        return "Failure to express, failure to fold into the predicted domain, or lack of detectable binding/activity would reject the hypothesis as a functional homolog."
    return "No phenotype change after knockout, or no in vitro activity after heterologous expression, would falsify the functional claim."


def ambient_hypothesis(row: dict[str, str]) -> str:
    source = fetch_source_annotation(row)
    if source:
        return f"Alternative: the protein has the function recorded in its current annotation ({source}), rather than the target enzyme activity."
    return "Alternative: the protein is a structural paralog without the target enzyme activity, or the observed evidence is an artifact of domain similarity."


def evidence_chain(row: dict[str, str]) -> str:
    parts = []
    if row.get("sequence_score", "").strip():
        parts.append(f"DIAMOND sequence evidence={row['sequence_score']}")
    if row.get("tm_score_mean", "").strip():
        parts.append(f"US-align TM={row['tm_score_mean']}")
    if row.get("deer_distance", "").strip():
        parts.append(f"DEER distance={row['deer_distance']}")
    if row.get("fedkea_final_result", "").strip():
        parts.append(f"FedKEA EC={row['fedkea_final_result']}")
    source = fetch_source_annotation(row)
    if source:
        parts.append(f"source_annotation={source}")
    return " -> ".join(parts) if parts else "no machine-generated screening evidence recorded"


def literature_citations(row: dict[str, str], literature_rows: list[dict[str, str]]) -> str:
    acc = row.get("protein_accession") or row.get("candidate_id") or ""
    organism = row.get("organism_or_strain") or ""
    matches = [
        lit for lit in literature_rows
        if (lit.get("protein_accession") or "") == acc
        or ((lit.get("candidate_id") or "") and (row.get("candidate_id") or "") and lit["candidate_id"] == row["candidate_id"])
        or ((lit.get("organism_or_strain") or "") and (organism or "") and lit["organism_or_strain"] == organism)
    ]
    refs = []
    for lit in matches:
        ref_type = lit.get("reference_type", "")
        ref_id = lit.get("reference_id", "")
        finding = lit.get("finding", "")
        if lit.get("verified", "").lower() not in ("yes", "true", "1"):
            continue
        if ref_id:
            refs.append(ref_id + (f" ({finding})" if finding else ""))
        elif finding:
            refs.append(finding)
    return "; ".join(refs)


def designer_notes(row: dict[str, str]) -> str:
    note = row.get("source_annotation_note", "")
    if note:
        return f"Start from the existing annotation note: {note}"
    return "Generate from sequencing/genome annotation and screening evidence; do not fabricate wet-lab data."


def provenance() -> str:
    return "plugin:summarize_candidates:v2:hypotheses"


def gene_metadata(row: dict[str, str], evidence_by_id: dict[str, dict[str, str]]) -> str:
    candidate_id = row.get("candidate_id") or row.get("protein_accession") or ""
    ev = evidence_by_id.get(candidate_id, {})
    pieces = []
    locus = ev.get("locus_tag") or row.get("source_locus_tag") or ""
    if locus:
        pieces.append(locus)
    location = ev.get("location") or ""
    if location:
        pieces.append(location)
    note = row.get("source_annotation_note") or ""
    if note and note not in pieces:
        pieces.append(note)
    return ";".join(pieces)


def _card_fields(project: dict[str, Any], project_path: Path | None) -> dict[str, str]:
    card = project_card(project, project_path)
    return {
        "enzyme": str(card.get("enzyme_name") or "").strip(),
        "ec": str(card.get("ec") or "").strip(),
        "reaction": str(card.get("reaction") or "").strip(),
        "substrate": str(card.get("substrate") or "").strip(),
        "product": str(card.get("product") or "").strip(),
        "cofactor": str(card.get("cofactor") or "").strip(),
        "fold": str(card.get("structural_fold") or "").strip(),
        "catalytic": str(card.get("catalytic_residues_file") or "").strip(),
    }


def write_experimental_design(
    outdir: Path,
    project: dict[str, Any],
    project_path: Path | None,
    final_rows: list[dict[str, str]],
    hypothesis_rows: list[dict[str, str]],
) -> Path:
    """把候选表与假设表变成一份能照着做的实验方案。

    `experimental_hypotheses.tsv` 回答"什么情况算被证伪"，但不回答"订什么基因、怎么表达、测什么、
    先做哪个"——后者才是实验台前或外包公司需要的东西。这里每个候选相关的数值都来自目标卡片、
    候选表或假设表，协议选择标为建议并写明理由，不凭空补参数。
    """
    card = _card_fields(project, project_path)
    by_accession = {row.get("protein_accession", ""): row for row in hypothesis_rows}

    def cell_text(value: str, limit: int = 70) -> str:
        """Make a value safe inside a markdown table cell.

        Accessions look like `sp|P39451|ADHP_ECOLI`; an unescaped pipe splits the cell and shifts every
        later column, which silently corrupts the table.
        """
        text = (value or "").replace("|", "\\|").replace("\n", " ").strip()
        return text if len(text) <= limit else text[: limit - 1] + "…"

    def product_of(annotation: str) -> str:
        """The annotation starts with the NCBI boilerplate; the product is what follows it."""
        text = annotation or ""
        marker = 'Protein Homology." '
        if marker in text:
            text = text.split(marker, 1)[1]
        elif text.startswith("Derived by automated"):
            text = text.split('"', 1)[-1]
        return cell_text(text.strip(' "'), 60)
    lines: list[str] = []
    add = lines.append

    title = card["enzyme"] or "目标酶"
    ec = f"（EC {card['ec']}）" if card["ec"] else ""
    add(f"# 实验方案：{title}{ec}")
    add("")
    add("由目标卡片与排序后的候选自动生成。所有候选相关数值来自 `final_target_candidates.tsv` /")
    add("`experimental_hypotheses.tsv`；协议部分是针对该读出的建议，请按实验室标准流程调整。")
    add("")

    add("## 1. 什么算成功")
    add("")
    if card["reaction"]:
        add(f"- 受试反应：{card['reaction']}")
    if card["substrate"] and card["product"]:
        add(f"- 读出：{card['substrate']} 的消耗与 {card['product']} 的生成")
    if card["cofactor"]:
        add(f"- 辅因子：{card['cofactor']}（依赖辅因子的读出是最便宜的独立验证）")
    add("- **支持假设**：纯化蛋白使底物转化高于阴性对照，且随时间与蛋白浓度增加，至少三次生物学重复一致。")
    add("- **证伪**：在阳性对照成立的条件下降解仍不高于阴性对照上限。阳性对照失败或蛋白不溶属于")
    add("  **不可判定**，不是阴性——这条区分决定了「一批失败的测定」会不会被读成「没有功能」。")
    add("")

    add("## 2. 候选与推进顺序")
    add("")
    if final_rows:
        add("| 顺序 | 候选蛋白 | 来源菌 | 证据基础 | 最近的特征化同源物 | identity / coverage | 现有注释 |")
        add("| --- | --- | --- | --- | --- | --- | --- |")
        for row in final_rows:
            add(
                f"| {row.get('final_rank', '')} | {cell_text(row.get('protein_accession', ''))} | "
                f"{cell_text(row.get('organism_or_strain', ''))} | {cell_text(row.get('evidence_base', ''))} | "
                f"{cell_text(row.get('representative_id', ''))} | "
                f"{row.get('pident', '')}% / {row.get('query_coverage', '')}% | "
                f"{product_of(row.get('source_annotation', ''))} |"
            )
        add("")
        first = final_rows[0]
        add(f"先做 **{first.get('protein_accession', '')}**：排序第一，且它的最近同源物 "
            f"**{first.get('representative_id', '')}** 可以直接当阳性对照买/要。")
        if len(final_rows) > 1:
            add("其余候选按表中顺序推进；每个候选独立判定，不要用「前一个没活性」当作后面不做的理由。")
    else:
        add("最终候选表为空，先读 `final_target_candidates_note.md`，不要直接下单。")
        add("通常先补上缺失的验证步骤，或按说明放宽交付规则。")
    add("")

    add("## 3. 阶段一：基因合成与克隆")
    add("")
    add("- 按 *E. coli* 密码子优化每条 CDS；原始序列留档备查。")
    add("- 默认构建：N 端 His6-SUMO（可切除）在 pET28a 衍生载体上；若标签可能干扰催化或寡聚化，同时做无标签版本。")
    add("- 每个候选订一条构建，另外订：")
    add("  - 催化失活突变体（按卡片 `catalytic_residues_file` 指定位点；若没有该文件，用最近同源物的")
    add("    金属配位或活性位点残基），")
    add("  - 空载体，作为宿主背景对照。")
    add("")

    add("## 4. 阶段二：表达与纯化")
    add("")
    add("- 宿主：BL21(DE3)；若预期二硫键或稀有密码子，改用 SHuffle / Rosetta-gami。")
    add("- 诱导：0.2–0.5 mM IPTG，16–18 °C 过夜；保留 37 °C / 3 h 作为备选条件。")
    add("- 立刻记录可溶/包涵体分布：只在沉淀里出现时先换条件（降温、换标签、共表达伴侣），再谈测定。")
    add("- 纯化：金属亲和 → 分子筛；记录最终缓冲液成分，因为它可能模拟或抑制读出。")
    add("")

    add("## 5. 阶段三：体外活性测定")
    add("")
    add(f"- 底物：{card['substrate'] or '按卡片定义'}；产物标准品：{card['product'] or '按卡片定义'}。")
    add("- 检测方式（按优先级）：")
    add("  1. LC-MS 或 HPLC 定量底物与产物（特异性最好，需要产物标准品）；")
    add("  2. 340 nm 偶联读数——仅在消耗/生成 NAD(P)H 且纯化后没有其他同类活性时有效；")
    add("  3. 荧光或显色底物类似物做筛选读出，阳性必须用方法 1 复核。")
    add("- 每块板都带：阳性对照（上面的特征化同源物）、催化失活突变体、空载体裂解液、无酶空白。")
    add("- 条件：底物浓度取最近同源物报道的 Km 附近，pH 7.0–8.0，37 °C，至少三次生物学重复；")
    add("  任何阳性结果都要补蛋白滴定与时间曲线。")
    add("")

    add("## 6. 阶段四：特异性（阶段三出现阳性之后再做）")
    add("")
    add("- 测 2–3 个相近底物，看活性是目标反应还是一般性活性——宽底物谱是结果，不是干扰。")
    add("- 用产物做竞争实验、核对化学计量比，把「真转化」和「偶联/间接效应」分开。")
    add("")

    add("## 7. 判定规则（数据回来之前就固定）")
    add("")
    predictions = {
        (by_accession.get(row.get("protein_accession", ""), {}).get("testable_prediction") or "").strip()
        for row in final_rows
    }
    falsifications = {
        (by_accession.get(row.get("protein_accession", ""), {}).get("falsification_criteria") or "").strip()
        for row in final_rows
    }
    if len(predictions) == 1 and len(falsifications) == 1:
        # one shared rule, stated once: repeating an identical sentence in four rows hides the parts
        # that actually differ between candidates
        add(f"- 可检验预测：{cell_text(next(iter(predictions)), 400) if predictions else '见 hypotheses 表'}")
        add(f"- 判为证伪：{cell_text(next(iter(falsifications)), 400) if falsifications else '见 hypotheses 表'}")
        add("")
        add("| 候选蛋白 | 现有注释 | 与最近同源物一致度 | 阴性时的替代解释 |")
        add("| --- | --- | --- | --- |")
        for row in final_rows:
            accession = row.get("protein_accession", "")
            hyp = by_accession.get(accession, {})
            ambient = (hyp.get("ambient_hypothesis") or "").replace("Alternative: ", "", 1)
            # the generated text quotes the NCBI boilerplate; drop it so the alternative reads as a
            # statement about the protein rather than about the annotation pipeline
            ambient = re.sub(r"\s*\(Derived by automated[^)]*\)", "", ambient)
            add(
                f"| {cell_text(accession, 30)} | {product_of(row.get('source_annotation', ''))} | "
                f"{row.get('pident', '')}% / {row.get('query_coverage', '')}% | {cell_text(ambient, 90)} |"
            )
    else:
        add("| 候选蛋白 | 可检验预测 | 判为证伪的条件 |")
        add("| --- | --- | --- |")
        for row in final_rows:
            accession = row.get("protein_accession", "")
            hyp = by_accession.get(accession, {})
            add(
                f"| {cell_text(accession, 30)} | {cell_text(hyp.get('testable_prediction', ''), 140)} | "
                f"{cell_text(hyp.get('falsification_criteria', ''), 140)} |"
            )
    add("")
    add("规则必须写在数据之前；每个候选的完整假设与替代解释见 `experimental_hypotheses.tsv`。")
    add("")

    add("## 8. 风险与替代方案")
    add("")
    add("| 风险 | 先做什么 |")
    add("| --- | --- |")
    add("| 蛋白不溶 | 降低诱导温度、换标签/载体、试 SHuffle 或共表达伴侣 |")
    add("| 可溶但无活性 | 裂解液补辅因子、切除标签、换 pH/缓冲体系 |")
    add("| 活性低于检测限 | 浓缩、延长孵育，把偶联读数换成 LC-MS |")
    add("| 所有对照都有活性 | 读出本身不特异，先换 LC-MS，再谈结论 |")
    add("| 阳性对照失败 | 停下来修方法；此时的阴性结果不可解释 |")
    add("")

    add("## 9. 如果要外包")
    add("")
    add("把候选与规则交给 `build_cro_work_order.py` 生成可直接询价的委托单，而不是重写这份方案：")
    add("")
    add("```bash")
    add("python3 scripts/build_cro_work_order.py --card <target_function_card.json> \\")
    add("    --candidates outputs/task/final_target_candidates.tsv \\")
    add("    --sequences outputs/task/candidate_sequences/candidate_proteins.faa \\")
    add("    --outdir outputs/task/cro_package --scope candidates")
    add("```")
    add("")
    add("它复用同一批候选与同一套预先注册的判定规则，价格与周期留空由承接方填写。")
    add("")

    path = outdir / "experimental_design.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scored", type=Path, required=True, help="scored_candidates_full.tsv.")
    parser.add_argument("--gene-evidence", type=Path, help="candidate_gene_evidence.tsv.")
    parser.add_argument("--literature", type=Path, help="Optional verified literature_evidence.tsv.")
    parser.add_argument("--project", type=Path, help="Project JSON with candidate_sequences metadata.")
    parser.add_argument(
        "--outdir",
        type=Path,
        default=Path("."),
        help="Directory to write final artifacts. Defaults to the current directory.",
    )
    parser.add_argument(
        "--decisions",
        default=None,
        help="environment.json holding recorded decisions; a delivery_rules decision is checked "
             "when the final table would be empty.",
    )
    parser.add_argument(
        "--final-rules",
        default="USALIGN_TARGET_EC,SEQUENCE_ANNOTATION_CONFIRMED",
        help="Comma-separated priority rules included in final_target_candidates.tsv.",
    )
    return parser.parse_args(argv)


def project_card(project: dict, project_path: Path | None = None) -> dict:
    """The card may be inline (a dict) or a path relative to project.json (a string).

    Every project generated from a card file stores the path, so treating it as a dict crashed
    with "'str' object has no attribute 'get'" on the documented workflow.
    """
    card = project.get("target_function_card") or {}
    if isinstance(card, str):
        candidates_path = [Path(card)]
        if project_path is not None:
            candidates_path.insert(0, project_path.parent / card)
        for candidate in candidates_path:
            if candidate.is_file():
                try:
                    return json.loads(candidate.read_text(encoding="utf-8"))
                except Exception:
                    return {}
        return {}
    if isinstance(card, dict):
        return card
    return {}


def write_no_candidate_delivery(outdir: Path, scored_path: Path, project_path: str | None) -> None:
    """A zero-hit screen is a result, not a crash.

    Summarising used to abort with "no candidate rows", so a legitimate "nothing passed the
    thresholds" run produced no deliverable at all and the completeness check called it incomplete.
    The delivery is an empty table plus a note that says what was screened and what to try next.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    write_tsv(outdir / "final_target_candidates.tsv", FINAL_FIELDS, [])
    write_tsv(outdir / "high_confidence_candidate_summary.tsv", SUMMARY_FIELDS, [])
    write_tsv(outdir / "experimental_hypotheses.tsv", HYPOTHESIS_FIELDS, [])
    card = project_card({"target_function_card": (project_path or "")}, Path(project_path) if project_path else None)
    ec = str(card.get("ec") or "").strip()
    name = str(card.get("enzyme_name") or card.get("target_name") or "").strip()
    lines = [
        "# Why final_target_candidates.tsv is empty",
        "",
        f"No candidate passed the sequence screening thresholds for `{name or 'the target'}`"
        + (f" (EC {ec})" if ec else "") + ".",
        f"The scored table `{scored_path.name}` has zero data rows, so there is nothing to rank.",
        "",
        "This is a real result, not a failed run: nothing in the candidate proteome matched the "
        "reference set at the configured identity/coverage/E-value cut-offs.",
        "",
        "What to try, in order:",
        "",
        "1. Confirm the reference set actually covers the target — count the templates and check "
        "whether they are host-only, which will miss a bacterial fold.",
        "2. Widen the cut-offs deliberately and record the change: "
        "`--identity 15 --coverage 0.5` (say so in the report; a loosened threshold is a different "
        "claim).",
        "3. Switch channel: if candidate structure files exist, US-align against the templates; "
        "sequence identity is a poor guide below ~20%.",
        "4. Accept the negative and write it up: a statement of no sequence-level candidate is a "
        "finding when the search space and thresholds are stated.",
        "",
    ]
    (outdir / "final_target_candidates_note.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote an empty delivery set with an explanation in {outdir}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = read_tsv(args.scored)
    if not rows:
        write_no_candidate_delivery(args.outdir, args.scored, args.project)
        return 0
    evidence_rows = read_tsv(args.gene_evidence) if args.gene_evidence else []
    evidence_by_id = {row.get("candidate_id") or row.get("protein_accession") or "": row for row in evidence_rows if row}
    literature_rows = read_tsv(args.literature) if args.literature else []
    candidates, genomes = load_candidate_paths(str(args.project) if args.project else None)
    project = {}
    if args.project and Path(args.project).is_file():
        try:
            project = json.loads(Path(args.project).read_text(encoding="utf-8"))
        except Exception:
            project = {}
    final_rules = {rule.strip() for rule in args.final_rules.split(",") if rule.strip()}

    summary_rows: list[dict[str, str]] = []
    final_rows: list[dict[str, str]] = []
    target_ec = str(project_card(project, Path(args.project) if args.project else None).get("ec") or "").strip()
    hypothesis_rows: list[dict[str, str]] = []
    for row in rows:
        acc = row.get("protein_accession") or row.get("candidate_id") or ""
        candidate_id = row.get("candidate_id") or acc
        meta = candidates.get(acc, {})
        organism = row.get("organism_or_strain") or meta.get("source_genome", "")
        summary = {
            "overall_rank": row.get("overall_rank", ""),
            "protein_accession": acc,
            "organism_or_strain": organism,
            "evidence_base": evidence_base(row),
            "tm_score_mean": row.get("tm_score_mean", ""),
            "structural_score": row.get("structural_score", ""),
            "deer_distance": row.get("deer_distance", ""),
            "deer_rank": row.get("deer_rank", ""),
            "source_annotation": fetch_source_annotation(row),
            "gene_metadata": gene_metadata(row, evidence_by_id),
            "fedkea_ec": row.get("fedkea_final_result", ""),
            "fedkea_confidence": row.get("fedkea_ec_confidence", ""),
            "validation_status": validation_status(row),
            "verdict": verdict(row),
        }
        summary_rows.append(summary)

        hyp_ctx = target_context(project)
        if not hyp_ctx:
            hyp_ctx = "human-microbiome metabolic function specified in the project target card"
        hyp_rank = row.get("overall_rank", "")
        hypothesis_rows.append(
            {
                "overall_rank": hyp_rank,
                "protein_accession": acc,
                "organism_or_strain": organism,
                "candidate_id": candidate_id,
                "target_context": hyp_ctx,
                "hypothesis_statement": hypothesis_statement(row, project, hyp_ctx),
                "mechanistic_model": mechanistic_model(row, project),
                "testable_prediction": testable_prediction(row, target_ec),
                "critical_experiments": critical_experiments(row),
                "falsification_criteria": falsification_criteria(row),
                "ambient_hypothesis": ambient_hypothesis(row),
                "evidence_chain": evidence_chain(row),
                "literature_citations": literature_citations(row, literature_rows),
                "designer_notes": designer_notes(row),
                "provenance": provenance(),
            }
        )

        rule = row.get("priority_rule", row.get("priority_tier", ""))
        if rule in final_rules:
            protein_fasta = meta.get("protein_fasta") or ""
            cds_fasta = meta.get("cds_fasta") or ""
            if not protein_fasta and organism in genomes:
                protein_fasta = (genomes[organism] or {}).get("protein_fasta", "")
            if not cds_fasta and organism in genomes:
                cds_fasta = (genomes[organism] or {}).get("cds_fasta", "")
            ev = evidence_by_id.get(acc, {})
            gene_fasta = meta.get("gene_fasta") or ""
            if not gene_fasta:
                gene_fasta = "outputs/task/candidate_sequences/candidate_gene_sequences.fna"
            mature_fasta = "outputs/task/candidate_sequences/candidate_mature_proteins.faa"
            final_rows.append(
                {
                    "final_rank": str(len(final_rows) + 1),
                    "protein_accession": acc,
                    "organism_or_strain": organism,
                    "representative_id": row.get("representative_id", "") or meta.get("representative_id", ""),
                    "pident": row.get("pident", ""),
                    "query_coverage": row.get("query_coverage", ""),
                    "evalue": row.get("evalue", ""),
                    "evidence_base": evidence_base(row),
                    "tm_score_mean": row.get("tm_score_mean", ""),
                    "structural_score": row.get("structural_score", ""),
                    "source_annotation": fetch_source_annotation(row),
                    "locus_tag": ev.get("locus_tag", ""),
                    "location": ev.get("location", ""),
                    "fedkea_ec": row.get("fedkea_final_result", ""),
                    "fedkea_confidence": row.get("fedkea_ec_confidence", ""),
                    "fedkea_accepted_name": row.get("fedkea_accepted_name", ""),
                    "fedkea_other_names": row.get("fedkea_other_names", ""),
                    "validation_status": validation_status(row),
                    "protein_fasta": protein_fasta,
                    "cds_fasta": cds_fasta,
                    "gene_fasta": gene_fasta,
                    "gene_source": ev.get("gene_seq_source", ""),
                    "signalp_prediction": ev.get("signalp_prediction", ""),
                    "is_secreted": ev.get("is_secreted", ""),
                    "mature_protein_fasta": mature_fasta if ev.get("is_secreted") == "Yes" else "",
                }
            )

    # One row per candidate protein. A protein hit by several templates produced one row per
    # template, so the table showed the same accession repeatedly (24 rows for 4 proteins), which
    # reads as 24 candidates. Keep the best-ranked row per accession.
    deduped: list[dict[str, str]] = []
    seen: dict[str, dict[str, str]] = {}
    for row in final_rows:
        accession = (row.get("protein_accession") or "").strip()
        if not accession:
            deduped.append(row)
            continue
        current = seen.get(accession)
        if current is None:
            seen[accession] = row
            deduped.append(row)
            continue
        try:
            better = float(row.get("overall_score") or 0) > float(current.get("overall_score") or 0)
        except (TypeError, ValueError):
            better = False
        if better:
            deduped[deduped.index(current)] = row
            seen[accession] = row
    collapsed = len(final_rows) - len(deduped)
    final_rows = deduped
    if collapsed:
        print(f"note: collapsed {collapsed} duplicate template alignment(s); one row per protein")

    summary_path = args.outdir / "high_confidence_candidate_summary.tsv"
    final_path = args.outdir / "final_target_candidates.tsv"
    hypotheses_path = args.outdir / "experimental_hypotheses.tsv"
    write_tsv(summary_path, SUMMARY_FIELDS, summary_rows)
    write_tsv(final_path, FINAL_FIELDS, final_rows)
    write_tsv(hypotheses_path, HYPOTHESIS_FIELDS, hypothesis_rows)
    design_path = write_experimental_design(
        args.outdir, project, Path(args.project) if args.project else None, final_rows, hypothesis_rows
    )
    print(f"wrote {summary_path} ({len(summary_rows)} rows)")
    print(f"wrote {final_path} ({len(final_rows)} rows)")
    print(f"wrote {design_path}")

    # An empty final table must never read as "nothing was found". When candidates exist but
    # none is in the delivery rule set, write the reason next to the table and say what widens it.
    if not final_rows and summary_rows:
        # The empty table is a delivery-rules decision, so ask it here instead of only noting it.
        decision_gate(
            getattr(args, "decisions", None),
            "delivery_rules",
            override=bool(args.final_rules and "OTHER_EC" in args.final_rules),
            why="交付表为空：要不要把 USALIGN_OTHER_EC 收进来，是科学判断",
        )
        tiers: dict[str, int] = {}
        for row in summary_rows:
            tier = row.get("priority_tier") or row.get("evidence_base") or "unknown"
            tiers[tier] = tiers.get(tier, 0) + 1
        note_path = args.outdir / "final_target_candidates_note.md"
        lines = [
            "# Why final_target_candidates.tsv is empty",
            "",
            f"{len(summary_rows)} candidate(s) were scored, but none matches the delivery rule set: "
            f"`{','.join(sorted(final_rules))}`.",
            "",
            "Tiers present:",
            "",
        ]
        lines += [f"- `{tier}`: {count}" for tier, count in sorted(tiers.items(), key=lambda kv: -kv[1])]
        lines += [
            "",
            "This is NOT the same as 'no candidate'. `USALIGN_OTHER_EC` means the protein is "
            "structurally similar to the target while FedKEA predicts a different EC: a shared "
            "fold can carry convergent or moonlighting activity and FedKEA is only a prediction, "
            "so such rows are candidates for experimental testing rather than exclusions.",
            "",
            "Before widening the rule set, check whether FedKEA was actually run. When US-align "
            "candidates exist but carry no FedKEA result, their tier is `USALIGN_UNVALIDATED` and no "
            "row can reach `USALIGN_TARGET_EC`:",
            "",
            "```bash",
            "# run FedKEA on the candidate FASTA, parse it, then merge it back in",
            "python3 scripts/parse_fedkea.py --binary-result <OUT>/binary_result.txt \\",
            "    --probability-csv <OUT>/enzyme_result_with_probability.csv \\",
            "    --confidence-csv <OUT>/enzyme_result_with_confidence.csv \\",
            "    --output outputs/task/fedkea_results.tsv",
            "python3 scripts/merge_candidates.py --sequence <seq>.tsv --structural <struct>.tsv \\",
            "    --fedkea outputs/task/fedkea_results.tsv --project project.json \\",
            "    --output outputs/task/combined_candidates.tsv",
            "```",
            "",
            "To deliver them without FedKEA, widen the rule set:",
            "",
            "```bash",
            "python3 scripts/summarize_candidates.py --scored outputs/task/scored_candidates.tsv \\",
            "    --project project.json --outdir outputs/task \\",
            "    --final-rules USALIGN_TARGET_EC,SEQUENCE_ANNOTATION_CONFIRMED,USALIGN_OTHER_EC",
            "```",
            "",
            "Their `testable_prediction` names both the target reaction and the FedKEA-predicted "
            "reaction, so the side-by-side assay settles it.",
            "",
        ]
        note_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"wrote {note_path} (final table empty by rule set, {len(summary_rows)} candidates exist)")
        print(
            f"note: final_target_candidates.tsv is empty because no candidate matches "
            f"{','.join(sorted(final_rules))}; {len(summary_rows)} candidate(s) exist under other "
            "tiers. See final_target_candidates_note.md and consider --final-rules.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
