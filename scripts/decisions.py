#!/usr/bin/env python3
"""The judgment points the plugin must not decide on the user's behalf.

Each decision names the stage at which it becomes relevant, because asking everything up front
is wrong: "may DEER run" only has meaning once US-align has left too few candidates, and "which
tiers does the delivery table contain" only matters when the table is being written. The stages
are what the scripts check when they reach that point; if the decision is still unanswered they
stop and print the options instead of applying a default.

Stages:

  start      before anything runs (candidate data)
  structure  when the structural branch is reached (structures, structure source)
  deer       when US-align left too few candidates
  ranking    when the delivery order is chosen
  delivery   when the delivery tables are written
"""

from __future__ import annotations

from typing import Any

DECISION_POINTS: dict[str, dict[str, Any]] = {
    "candidate_data": {
        "stage": "start",
        "question": "候选菌的蛋白组/基因组从哪来？",
        "options": [
            ("user_path", "我有文件，给你绝对路径", "必需字段：path（.faa/.fna/.gbff）"),
            ("download_ncbi", "我没有，帮我从 NCBI 下载", "必需字段：accession（GCF_/GCA_）或 species"),
            ("not_available", "暂时没有候选数据", "后续只能做目标卡片，不能做筛选"),
        ],
        "fields": ("path", "annotation_path", "accession", "species"),
    },
    "candidate_structures": {
        "stage": "structure",
        "question": "有没有候选菌的蛋白结构文件？",
        "options": [
            ("user_path", "有，给你结构目录", "必需字段：dir；建议 kind=experimental|predicted"),
            ("predict", "没有，先跑 structure-prediction", "需先回答结构来源（structure_source）"),
            ("skip", "没有，且这次不做结构分析", "只能得到 SEQUENCE_ONLY / 注释层结论"),
        ],
        "fields": ("dir", "kind"),
    },
    "structure_source": {
        "stage": "structure",
        "question": "需要预测结构时，接受哪种来源？",
        "options": [
            ("pdb_then_afdb", "实验结构优先，其次 AlphaFold DB（pLDDT>=60）", "默认，证据强度递减"),
            ("afdb_only", "只用 AlphaFold DB", "有 AFDB 模型即可，不找实验结构"),
            ("homology_ok", "允许同源建模", "有同源模板但无实验/预测结构时"),
            ("de_novo", "允许 de novo 预测", "完全没有模板，证据最弱，必须在报告里标注"),
        ],
        "fields": (),
    },
    "deer_fallback": {
        "stage": "deer",
        "question": "US-align 合格候选不足时，是否启用 DEER？",
        "options": [
            ("skip", "不启用（默认）", "只保留 US-align 结果"),
            ("run", "启用", "run_deer.py --allow-fallback 才放行；DEER 是 fallback 而非主筛"),
        ],
        "fields": (),
    },
    "ranking_policy": {
        "stage": "ranking",
        "question": "最终排序以什么为主键？",
        "options": [
            ("tm_first", "结构相似度（TM）优先（--rank-by structure）", "趋同/兼职酶不会被 EC 不一致压下去"),
            ("priority_first", "优先级层级优先（--rank-by priority）", "需要严格按 tier 排序时"),
        ],
        "fields": (),
    },
    "delivery_rules": {
        "stage": "delivery",
        "question": "交付表收哪些 tier？",
        "options": [
            ("strict", "只收已确认（快速通道 / USALIGN_TARGET_EC）", "交付表可能为空，需读说明文件"),
            ("include_other_ec", "同时收 USALIGN_OTHER_EC", "结构相似但 FedKEA 预测其他 EC，作为待验证候选"),
        ],
        "fields": (),
    },
}

STAGE_LABEL = {
    "start": "开始之前",
    "structure": "走到结构分析这一步时",
    "deer": "US-align 候选不足时",
    "ranking": "决定排序时",
    "delivery": "写交付表时",
}

DECISION_REQUIRED = {
    ("candidate_data", "user_path"): "path",
    ("candidate_data", "download_ncbi"): "accession",
    ("candidate_structures", "user_path"): "dir",
}


def points_for_stage(stage: str) -> list[str]:
    return [name for name, spec in DECISION_POINTS.items() if spec["stage"] == stage]


def render(name: str, number: int | None = None) -> str:
    spec = DECISION_POINTS[name]
    label = f"{number}. " if number is not None else ""
    lines = [f"{label}{spec['question']}"]
    for index, (option_id, text, note) in enumerate(spec["options"], 1):
        lines.append(f"   {index}) {text}   [{option_id}]")
        if note:
            lines.append(f"      → {note}")
    return "\n".join(lines)


def render_stage(stage: str) -> str:
    names = points_for_stage(stage)
    if not names:
        return ""
    head = f"这一步需要你判断（{STAGE_LABEL.get(stage, stage)}）："
    return head + "\n\n" + "\n\n".join(render(name, i) for i, name in enumerate(names, 1))


def check(name: str, value: Any) -> dict[str, Any]:
    spec = DECISION_POINTS[name]
    valid = {option_id for option_id, _text, _note in spec["options"]}
    if value is None:
        return {"status": "needs_decision", "choice": None,
                "detail": "用户还没选；把选项发给他，不要自己替他选"}
    if not isinstance(value, dict):
        return {"status": "invalid", "choice": None, "detail": "decision 必须是对象"}
    choice = value.get("choice")
    if choice not in valid:
        return {"status": "invalid", "choice": choice,
                "detail": f"choice 必须是 {', '.join(sorted(valid))}"}
    required = DECISION_REQUIRED.get((name, choice))
    if required and not str(value.get(required) or "").strip():
        return {"status": "needs_field", "choice": choice, "detail": f"选了 {choice}，但缺少 {required}"}
    if choice == "user_path" and name == "candidate_structures":
        kind = str(value.get("kind") or "").strip()
        if kind and kind not in ("experimental", "predicted"):
            return {"status": "invalid", "choice": choice,
                    "detail": "kind 只能是 experimental 或 predicted"}
    detail = f"choice={choice}"
    if name == "candidate_structures":
        kind = str(value.get("kind") or "").strip()
        if kind:
            detail += f" ({kind})"
    return {"status": "resolved", "choice": choice, "detail": detail}


def block_message(name: str, why: str = "") -> str:
    """The text a script prints when it reaches a stage and the decision is unanswered."""
    lines = ["DECISION REQUIRED" + (f": {why}" if why else "")]
    lines.append("")
    lines.append(render(name))
    lines.append("")
    lines.append("这一步停下来问用户，不要用默认值继续（默认值会改变结论含义）。")
    lines.append(f'回答后写进 environment.json: "decisions": {{"{name}": {{"choice": "<选项id>", ...}}}}')
    return "\n".join(lines)


def load_recorded(path: "str | None") -> dict:
    """Read decisions out of an environment.json, tolerating a bare decisions block."""
    if not path:
        return {}
    import json
    from pathlib import Path as _Path

    file = _Path(str(path))
    if not file.is_file():
        return {}
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(data.get("decisions"), dict):
        return data["decisions"]
    return data if isinstance(data, dict) else {}


def gate(path: "str | None", name: str, override: bool, why: str = "") -> bool:
    """True when the run may continue.

    A recorded decision that is unresolved blocks, with the options printed. An explicit CLI
    override is treated as the user having answered, but it is still named in the output so the
    choice is visible rather than silently assumed.
    """
    recorded = load_recorded(path).get(name)
    status = check(name, recorded)
    if status["status"] == "resolved":
        print(f"decision {name}: {status['detail']}")
        return True
    if override:
        print(
            f"decision {name}: not recorded in the decisions file, but the command line "
            "explicitly asked for it — proceeding on that instruction",
            file=__import__("sys").stderr,
        )
        return True
    print(block_message(name, why), file=__import__("sys").stderr)
    return False
