#!/usr/bin/env python3
"""Ask for — and verify — the execution environment before any workflow runs.

`preflight_inputs.py` checks whether the *task inputs* exist. This script checks
whether the *execution environment* exists: which host runs the job, where each
external tool lives, which environment variables a tool actually needs, which
databases are present, and whether the machine may reach the network.

It exists because the expensive failures are environmental, not scientific. In one
real run the same project lost time to: a tool invoked by absolute path without its
conda env on PATH, a second that needed PYTHONPATH, a third that hung trying to
download a checkpoint from Hugging Face on a machine with no network, a Bakta
database that was never installed, and a shared box already running 146 processes
from another project.

Two rules this script encodes:

- **Ask, do not guess.** `--ask` prints the questionnaire to send to the user. An
  absent answer is recorded as `unknown`, never as a default.
- **A path is not a working tool.** `--probe` runs a version command; a tool that
  cannot report a version is `unverified`, not `ready`.

Usage:

    # 1. print the questionnaire for the user
    python3 scripts/intake_environment.py --ask

    # 2. turn their answers into a file to fill in
    python3 scripts/intake_environment.py --init --output environment.json

    # 3. verify what is actually reachable from this terminal
    python3 scripts/intake_environment.py --probe --config environment.json \\
        --output-card environment_card.json --output-report environment_report.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# What each tool's resolved path and version output must look like. The digit rule alone
# was not enough: on CentOS 7 `/bin/echo --version` prints "echo (GNU coreutils) 8.22",
# which contains digits and made a coreutils binary pass as DIAMOND.
TOOL_TOKENS: dict[str, tuple[str, ...]] = {
    "diamond": ("diamond",),
    "cd-hit": ("cd-hit", "cdhit", "cd hit"),
    "usalign": ("us-align", "usalign", "tm-align", "tmalign"),
    "deer": ("deer",),
    "fedkea": ("fedkea",),
    "bakta": ("bakta",),
    "signalp": ("signalp",),
    "hmmsearch": ("hmmsearch", "hmmer"),
    "esmfold": ("esmfold",),
}

# Commands that exist on every machine and must never satisfy a probe for a real tool.
GENERIC_UTILITIES = {
    "echo", "printf", "cat", "true", "false", "yes", "sleep", "env",
    "sh", "bash", "zsh", "ls", "cp", "mv", "tee", "printenv",
}

GENERIC_OUTPUT_MARKERS = ("coreutils", "busybox", "gnu bash", "shell builtin")

TOOLS = [
    ("diamond", "DIAMOND", "序列筛选"),
    ("cd-hit", "CD-HIT", "去冗余"),
    ("usalign", "US-align", "结构比对"),
    ("deer", "DEER", "学习型结构检索（fallback / 深度检索）"),
    ("fedkea", "FedKEA", "酶 / EC 预测（本地）"),
    ("bakta", "Bakta", "基因组注释"),
    ("signalp", "SignalP", "信号肽预测"),
    ("hmmsearch", "HMMER hmmsearch", "家族普查（Pfam HMM）"),
    ("esmfold", "ESMFold", "de novo 结构预测"),
]

DATABASES = [
    ("BAKTA_DB_FULL", "Bakta 全库"),
    ("BAKTA_DB_LIGHT", "Bakta 轻库"),
    ("AFDB_DIR", "AlphaFold DB（全量或按 accession 缓存）"),
    ("PDB_MIRROR", "PDB 本地镜像"),
    ("UNIPROT_FASTA", "UniProt / Swiss-Prot FASTA"),
    ("DEER_CKPT", "DEER checkpoint"),
    ("FEDKEA_HOME", "FedKEA 安装目录"),
    ("GMPS_ROOT", "GMPS 结构数据（按物种分卷，肠道）"),
    ("GMPS_ANNOTATION", "GMPS 注释表（bacteria_final_annotation）"),
    ("GMPS_SPECIES_MAP", "GMPS 分卷-物种对照表"),
]

# The questionnaire is scoped by what the task actually needs. Asking about Bakta
# before knowing whether any genome is involved is noise, and asking about DEER before
# knowing whether US-align suffices is worse than noise.
TASK_PROFILES: dict[str, dict[str, Any]] = {
    "card": {
        "label": "只建目标卡片 / build the target card only",
        "groups": ("execution", "data"),
        "note": "不需要任何外部软件；只要目标定义清楚就能建卡。",
    },
    "screening": {
        "label": "序列筛选 / sequence screening",
        "groups": ("execution", "data", "tools_core", "network"),
        "note": "需要 DIAMOND + CD-HIT；若没有现成候选蛋白组，还要基因组来源。",
    },
    "structure": {
        "label": "序列 + 结构筛选 / sequence plus structure",
        "groups": ("execution", "data", "tools_core", "tools_structure", "network"),
        "note": "在序列筛选之上加 US-align；候选没有结构时还要 PDB/AFDB 或建模工具。",
    },
    "full": {
        "label": "完整流程 / full workflow",
        "groups": ("execution", "tools_all", "databases", "data", "network"),
        "note": "全部工具与数据库：注释、酶学预测、结构检索、文献。",
    },
}

# The two decisions the user must make before any screening. They are modelled as choices,
# not as prose, so the answer is recorded, machine-checkable, and impossible to silently assume.
DECISIONS: dict[str, dict[str, Any]] = {
    "candidate_data": {
        "question": "候选菌的蛋白组/基因组从哪来？",
        "options": [
            ("user_path", "我有文件，给你绝对路径", "必需字段：path（.faa/.fna/.gbff）"),
            ("download_ncbi", "我没有，帮我从 NCBI 下载", "必需字段：accession（GCF_/GCA_）或 species"),
            ("not_available", "暂时没有候选数据", "后续只能做目标卡片，不能做筛选"),
        ],
        "fields": ("path", "annotation_path", "accession", "species"),
    },
    "candidate_structures": {
        "question": "有没有候选菌的蛋白结构文件？",
        "options": [
            ("user_path", "有，给你结构目录", "必需字段：dir；建议 kind=experimental|predicted"),
            ("predict", "没有，先跑 structure-prediction", "PDB > AlphaFold DB pLDDT>=60 > 同源建模 > de novo"),
            ("skip", "没有，且这次不做结构分析", "只能得到 SEQUENCE_ONLY / 注释层结论"),
        ],
        "fields": ("dir", "kind"),
    },
    # The remaining judgment points. Each one changes what the answer means, so none of them
    # may be decided by the plugin on the user's behalf.
    "structure_source": {
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
        "question": "US-align 合格候选不足时，是否启用 DEER？",
        "options": [
            ("skip", "不启用（默认）", "只保留 US-align 结果"),
            ("run", "启用", "需要用 --allow-fallback 显式放行，DEER 是 fallback 而非主筛"),
        ],
        "fields": (),
    },
    "ranking_policy": {
        "question": "最终排序以什么为主键？",
        "options": [
            ("tm_first", "结构相似度（TM）优先（默认）", "趋同/兼职酶不会被 EC 不一致压下去"),
            ("priority_first", "优先级层级优先", "需要严格按 tier 排序时"),
        ],
        "fields": (),
    },
    "delivery_rules": {
        "question": "交付表收哪些 tier？",
        "options": [
            ("strict", "只收已确认（快速通道 / USALIGN_TARGET_EC）", "交付表可能为空，需读说明文件"),
            ("include_other_ec", "同时收 USALIGN_OTHER_EC", "结构相似但 FedKEA 预测其他 EC，作为待验证候选"),
        ],
        "fields": (),
    },
}

DECISION_REQUIRED = {
    ("candidate_data", "user_path"): "path",
    ("candidate_data", "download_ncbi"): "accession",
    ("candidate_structures", "user_path"): "dir",
}


def decision_question_text(name: str, number: int | None = None) -> str:
    spec = DECISIONS[name]
    label = f"{number}. " if number is not None else ""
    lines = [f"{label}{spec['question']}"]
    for index, (option_id, text, note) in enumerate(spec["options"], 1):
        lines.append(f"   {index}) {text}   [{option_id}]")
        if note:
            lines.append(f"      → {note}")
    return "\n".join(lines)


def check_decision(name: str, value: Any) -> dict[str, Any]:
    """Validate one recorded decision: an option must be chosen, and its required field filled."""
    spec = DECISIONS[name]
    valid = {option_id for option_id, _text, _note in spec["options"]}
    if value is None:
        return {"status": "needs_decision", "choice": None,
                "detail": "用户还没选；先把选项发给他，不要自己替他选"}
    if not isinstance(value, dict):
        return {"status": "invalid", "choice": None, "detail": "decision 必须是对象"}
    choice = value.get("choice")
    if choice not in valid:
        return {"status": "invalid", "choice": choice,
                "detail": f"choice 必须是 {', '.join(sorted(valid))}"}
    required = DECISION_REQUIRED.get((name, choice))
    if required and not (value.get(required) or "").strip():
        return {"status": "needs_field", "choice": choice,
                "detail": f"选了 {choice}，但缺少 {required}"}
    if choice == "user_path" and name == "candidate_structures":
        kind = (value.get("kind") or "").strip()
        if kind and kind not in ("experimental", "predicted"):
            return {"status": "invalid", "choice": choice,
                    "detail": "kind 只能是 experimental 或 predicted"}
    return {"status": "resolved", "choice": choice,
            "detail": f"choice={choice}" + (f" ({kind})" if name == "candidate_structures" and (value.get("kind") or "").strip() else "")}


GROUP_LABEL = {
    "execution": "执行位置与许可",
    "data": "数据路径",
    "tools_core": "序列筛选工具",
    "tools_structure": "结构工具",
    "tools_all": "全部外部软件",
    "databases": "数据库",
    "network": "网络与资源约束",
}

GROUP_TEXT = {
    "execution": """1. 在哪里跑？
   - 本机，还是远程服务器（host / 用户名 / 端口）？
   - 是否允许我这边直接连上去执行？还是只能我给命令、你来跑、把结果拿回来？
   - 工作目录（可写）是哪个？""",
    "data": """数据路径（两个必须单独问清的问题，别替用户猜）

   【必问 1】候选数据在哪？
   - 候选菌的蛋白组（.faa）或基因组（.fna/.gbff）的绝对路径？
   - 有没有对应的注释文件（.gbff/.gff）？
   - 如果用户说没有：问"要我从 NCBI 下载吗？给 GCF/GCA 号或物种名"——不要自己挑一个装配。

   【必问 2】有没有候选菌的结构文件？
   - 有：结构目录的绝对路径（PDB/mmCIF），是实验结构还是预测结构？
   - 没有：问"是否先跑 structure-prediction（PDB > AlphaFold DB pLDDT>=60 > 同源建模 > de novo）？"

   另外：目标序列 / 目标结构模板（有就给绝对路径，没有就说没有）；这些文件在哪个机器上？""",
    "tools_core": """2. 序列筛选工具（有就给绝对路径，没有就说没有）
   DIAMOND、CD-HIT
   - 是否依赖 conda 环境或特殊环境变量？""",
    "tools_structure": """3. 结构工具
   US-align（必需）；DEER（只在 US-align 候选不足时才用）
   - 候选结构从哪来：已有的 PDB/AFDB 文件、还是要现场预测（ESMFold / 同源建模）？
   - 若用 DEER：checkpoint 与脚本路径？""",
    "tools_all": """4. 全部外部软件（有就给绝对路径）
   DIAMOND / CD-HIT / US-align / DEER / FedKEA / Bakta / SignalP / ESMFold
   - 每个是否需要 conda 环境或环境变量？
     （已知坑：FedKEA 调裸 `python` 需 PATH + LD_LIBRARY_PATH；SignalP 需 PYTHONPATH；
       DEER 需 PATH + PYTHONPATH，且无外网时必须离线）""",
    "databases": """5. 数据库
   - Bakta：全库还是轻库，路径？
   - AlphaFold DB / PDB：本地镜像还是按需下载？
   - FedKEA 权重 / DEER checkpoint 在哪？
   - GMPS（可选，仅肠道）：注释表/结构卷路径？""",
    "network": """6. 约束
   - 这台机器能联网吗？（NCBI / RCSB / HuggingFace）
   - 磁盘配额、单任务时限、有没有不能碰的目录？""",
}

PERMISSION_QUESTION = "另外请明确一句：**你允许我在本机直接执行脚本，还是所有命令都由你手动运行？**"


QUESTIONNAIRE_TEMPLATE = """\
在跑任何流程之前，请先回答下面 6 组问题。不知道的直接说“不知道”——我不会替你猜，
也不会假设某个软件已经装好。（回答后我会写进 environment.json 并逐项验证。）

0. 必须先做的判断（插件不会替你选）
{all_choices}

1. 在哪里跑？
   - 本机，还是远程服务器（host / 用户名）？
   - 是否允许我这边直接连上去执行？还是只能我给命令、你来跑、把结果拿回来？
   - 工作目录（可写）是哪个？

2. 机器资源
   - CPU 核数、内存、有没有 GPU？
   - 是不是共享机器（有没有别人正在占大量进程）？
   - 有调度器吗（slurm / PBS），还是直接跑？

3. 外部软件（有就给绝对路径，没有就说没有）
   DIAMOND / CD-HIT / US-align / DEER / FedKEA / Bakta / SignalP / hmmsearch / ESMFold
   - 每个软件是否依赖 conda 环境或特殊环境变量？
     （已知坑：FedKEA 调裸 `python` 需 PATH + LD_LIBRARY_PATH；SignalP 需 PYTHONPATH；
       DEER 需 PATH + PYTHONPATH，且无外网时必须离线）

4. 数据库
   - Bakta：全库还是轻库，路径？
   - AlphaFold DB：全量镜像，还是按需下载单个模型？
   - PDB：本地镜像路径？如果只能联网下载，说明网络情况。
   - FedKEA 权重 / DEER checkpoint 在哪里？

5. 数据
   - 候选蛋白 FASTA / 基因组 FASTA / 注释 gbff / 结构文件目录，各自的路径。
   - 目标结构（模板）用实验结构还是预测模型？

6. 约束
   - 这台机器能联网吗？（NCBI / RCSB / HuggingFace）
   - 磁盘配额、单任务时限、有没有不能碰的目录？

另外请明确一句：**你允许我在本机直接执行脚本，还是所有命令都由你手动运行？**
"""
QUESTIONNAIRE = QUESTIONNAIRE_TEMPLATE.format(
    all_choices="\n\n".join(decision_question_text(name) for name in DECISIONS)
)


def skeleton() -> dict[str, Any]:
    return {
        "_readme": [
            "逐项填写；不确定就保留 null，probe 会把它记成 unknown 而不是猜测。",
            "execution.allow_local_execution 决定我能不能在本机直接跑：true / false / \"unknown\"。",
            "tools.<name> 支持三种写法：null（没有）、字符串（可执行文件路径或命令名）、或对象 {path, env, version_cmd}。",
            "env 里写这个工具必须的环境变量，例如 {\"LD_LIBRARY_PATH\": \"/path/envs/fedkea/lib\"}。",
        ],
        "execution": {
            "host": None,
            "user": None,
            "access": None,  # "local" | "ssh" | "user_only"
            "allow_local_execution": "unknown",  # true | false | "unknown"
            "workdir": None,
            "cpu_cores": None,
            "memory_gb": None,
            "gpu": None,
            "scheduler": None,
            "shared_machine": "unknown",
        },
        "decisions": {name: {"choice": None} for name in DECISIONS},
        "tools": {name: None for name, _, _ in TOOLS},
        "databases": {name: None for name, _ in DATABASES},
        "data": {
            "candidate_proteome_fasta": None,
            "candidate_genome_fasta": None,
            "candidate_annotation_gbff": None,
            "candidate_structure_dir": None,
            "target_structure": None,
        },
        "constraints": {
            "network": "unknown",  # "yes" | "no" | "unknown"
            "network_hosts": [],  # hosts to probe when --check-network is given
            "disk_quota": None,
            "job_time_limit": None,
        },
    }


# ---------------------------------------------------------------------------
# probe helpers
# ---------------------------------------------------------------------------


def resolve_executable(spec: Any) -> tuple[str | None, dict[str, str]]:
    """Return (path, extra_env) for a tool spec that may be a string or object."""
    if spec is None:
        return None, {}
    if isinstance(spec, str):
        return spec, {}
    if isinstance(spec, dict):
        path = spec.get("path")
        env = {str(k): str(v) for k, v in (spec.get("env") or {}).items()}
        return (str(path) if path else None), env
    return None, {}


def version_of(
    path: str, env: dict[str, str], timeout: int = 60, tool: str | None = None
) -> tuple[str | None, str]:
    """Find a version banner that belongs to THIS tool.

    Three things must agree before a binary counts as the tool: its name (or its banner)
    must mention the tool, the banner must carry a version number, and it must not be a
    generic utility reporting its own version. Found the hard way on CentOS 7, where
    `/bin/echo --version` prints "echo (GNU coreutils) 8.22" and made a coreutils binary
    pass as DIAMOND.

    Some tools have no version flag at all: US-align treats `--version` as a file name and
    only prints its banner when invoked with no arguments. That is why the flag list ends
    with a bare invocation, and why every line is scanned instead of only the first.

    The timeout is generous because a cold Python entry point on an NFS home can take tens
    of seconds the first time (Bakta timed out at 20s on node7 and returned instantly on the
    second run).
    """
    name = os.path.basename(os.path.realpath(path)).lower()
    if name in GENERIC_UTILITIES:
        return None, f"解析到的是通用命令（{name}），不是 {tool or '该工具'}"

    tokens = tuple(t for t in TOOL_TOKENS.get(tool or "", (tool.lower() if tool else "",)) if t)
    full_env = {**os.environ, **env}
    first_line = ""
    for flag in ("--version", "-version", "-v", "version", None):
        argv = [path] if flag is None else [path, flag]
        label = "（无参数）" if flag is None else f"`{flag}`"
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout,
                env=full_env, cwd=os.path.expanduser("~"),
            )
        except FileNotFoundError:
            return None, "not found"
        except subprocess.TimeoutExpired:
            return None, (
                f"在 {timeout}s 内没有返回（{label}）；"
                "冷启动在 NFS 家目录上可能很慢，重跑一次或手动确认"
            )
        except PermissionError:
            return None, "not executable (permission denied)"
        except OSError as exc:
            return None, f"cannot run: {exc}"

        text = (proc.stdout or "") + (proc.stderr or "")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if lines and not first_line:
            first_line = lines[0]
        for line in lines:
            lowered = line.lower()
            if any(marker in lowered or marker in name for marker in GENERIC_OUTPUT_MARKERS):
                return None, f"解析到的是通用命令（{name}），不是 {tool or '该工具'}"
            if not any(ch.isdigit() for ch in line):
                continue
            if tokens and not any(token in lowered or token in name for token in tokens):
                continue  # this line is not about our tool; keep looking
            return line, "ok"

    if first_line:
        return None, f"输出不含 {tool or '该工具'} 的版本标识: {first_line[:60]!r}"
    return None, "ran but reported no version"


def probe_tool(name: str, spec: Any) -> dict[str, Any]:
    path, env = resolve_executable(spec)
    if spec is None:
        return {"status": "not_provided", "detail": "用户未提供，按“没有”处理"}
    if not path:
        return {"status": "unknown", "detail": "已声明但路径为空"}
    resolved = path if Path(path).is_absolute() else (shutil.which(path) or "")
    if not resolved or not Path(resolved).exists():
        return {"status": "missing", "detail": f"找不到可执行文件: {path}", "declared": path}

    missing_env = [k for k in env if not os.environ.get(k) and not Path(str(env[k])).exists()]

    # DEER / FedKEA / ESMFold are invoked as `python <script>`; there is no version banner
    # to check, so compile the script instead of pretending a python banner proved anything.
    if Path(resolved).suffix.lower() == ".py":
        if name in ("deer", "fedkea", "esmfold"):
            python = shutil.which("python3") or shutil.which("python")
            if not python:
                return {"status": "unverified", "declared": path, "resolved": resolved,
                        "version": None, "detail": "脚本存在，但找不到 python 解释器，未做语法检查",
                        "env": env, "env_paths_missing": missing_env}
            try:
                proc = subprocess.run(
                    [python, "-c",
                     "import ast,sys; ast.parse(open(sys.argv[1], encoding='utf-8', "
                     "errors='replace').read(), sys.argv[1])",
                     resolved],
                    capture_output=True, text=True, timeout=30,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                return {"status": "unverified", "declared": path, "resolved": resolved,
                        "version": None, "detail": f"语法检查未完成: {exc}",
                        "env": env, "env_paths_missing": missing_env}
            if proc.returncode == 0:
                if missing_env:
                    return {"status": "unverified", "declared": path, "resolved": resolved,
                            "version": None,
                            "detail": "脚本语法检查通过，但声明的环境变量路径不存在: "
                                      + ", ".join(missing_env),
                            "env": env, "env_paths_missing": missing_env}
                return {"status": "ready", "declared": path, "resolved": resolved,
                        "version": None, "detail": "脚本语法检查通过（未执行，避免副作用）",
                        "env": env, "env_paths_missing": []}
            tail = (proc.stderr or "").strip().splitlines()
            return {"status": "unverified", "declared": path, "resolved": resolved,
                    "version": None, "detail": f"脚本语法检查失败: {tail[-1][:120] if tail else 'unknown'}",
                    "env": env, "env_paths_missing": []}

    version, why = version_of(resolved, env, tool=name)
    status = "ready" if version else "unverified"
    if missing_env:
        # A tool whose required library/env path does not exist will fail at run
        # time even if `--version` happened to work. Never call that ready.
        status = "unverified"
        why = f"{why}; 声明的环境变量路径不存在: {', '.join(missing_env)}"
    return {
        "status": status,
        "declared": path,
        "resolved": resolved,
        "version": version,
        "detail": why,
        "env": env,
        "env_paths_missing": missing_env,
    }


def probe_path(kind: str, value: Any) -> dict[str, Any]:
    if value is None:
        return {"status": "not_provided"}
    path = Path(str(value)).expanduser()
    if not path.exists():
        return {"status": "missing", "path": str(path)}
    if kind == "dir_or_file":
        # some artifacts are legitimately either (a checkpoint file, or the directory
        # that contains it); accept both, and say which one was found
        if path.is_dir():
            entries = sum(1 for _ in path.iterdir())
            if entries == 0:
                return {"status": "unverified", "path": str(path), "detail": "目录为空"}
            return {"status": "ready", "path": str(path), "kind": "directory", "entries": entries}
        if path.is_file():
            size = path.stat().st_size
            if size == 0:
                return {"status": "unverified", "path": str(path), "detail": "文件为空"}
            return {"status": "ready", "path": str(path), "kind": "file", "bytes": size}
        return {"status": "unverified", "path": str(path), "detail": "既不是文件也不是目录"}
    if kind == "dir":
        if not path.is_dir():
            return {"status": "not_a_directory", "path": str(path)}
        try:
            nested = sum(1 for _ in path.iterdir())
        except OSError as exc:
            return {"status": "unreadable", "path": str(path), "detail": str(exc)}
        writable = os.access(path, os.W_OK)
        return {"status": "ready", "path": str(path), "entries": nested, "writable": writable}
    if not path.is_file():
        return {"status": "not_a_file", "path": str(path)}
    return {"status": "ready", "path": str(path), "bytes": path.stat().st_size}


def probe_ssh(host: str, port: int = 22, user: str | None = None,
              run_command: bool = False, timeout: float = 6.0) -> dict[str, Any]:
    """Check whether the declared execution host is actually reachable.

    Two levels, because they fail differently: a TCP connect proves the port is open,
    while a BatchMode ssh proves the credentials already work without a password. Never
    prompts, never stores credentials, and never retries with a password.
    """
    result: dict[str, Any] = {"host": host, "port": port, "user": user, "tcp": False}
    try:
        with socket.create_connection((host, port), timeout=timeout):
            result["tcp"] = True
    except OSError as exc:
        result["detail"] = f"TCP {host}:{port} 不可达: {exc}"
        result["reachable"] = False
        return result

    if not run_command:
        result["reachable"] = True
        result["detail"] = f"TCP {host}:{port} 可连接（未测试登录）"
        return result

    target = f"{user}@{host}" if user else host
    try:
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={int(timeout)}",
             "-o", "StrictHostKeyChecking=accept-new", target, "true"],
            capture_output=True, text=True, timeout=timeout + 10,
        )
    except FileNotFoundError:
        result["reachable"] = True
        result["detail"] = "TCP 可连接，但本机没有 ssh 客户端，未测试登录"
        return result
    except subprocess.TimeoutExpired:
        result["reachable"] = True
        result["detail"] = "TCP 可连接，但 ssh 登录超时（可能需要密码或跳板机）"
        return result
    result["reachable"] = proc.returncode == 0
    result["ssh_exit"] = proc.returncode
    if proc.returncode == 0:
        result["detail"] = f"ssh {target} 免密登录成功"
    else:
        message = (proc.stderr or "").strip().splitlines()
        result["detail"] = (
            "TCP 可连接，但 BatchMode 登录失败（交互式密码或密钥未配置）"
            + (f": {message[-1][:120]}" if message else "")
        )
    return result


def probe_network(host: str, timeout: float = 4.0) -> dict[str, Any]:
    parsed = urlparse(host if "://" in host else f"//{host}")
    target = parsed.hostname or host
    port = parsed.port or (443 if parsed.scheme in ("https", "") else 80)
    try:
        with socket.create_connection((target, port), timeout=timeout):
            return {"host": host, "reachable": True, "port": port}
    except OSError as exc:
        return {"host": host, "reachable": False, "port": port, "detail": str(exc)}


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

STATUS_LABEL = {
    "ready": "READY",
    "unverified": "UNVERIFIED",
    "missing": "MISSING",
    "not_provided": "— 未提供",
    "unknown": "UNKNOWN",
    "not_a_directory": "NOT A DIR",
    "not_a_file": "NOT A FILE",
    "unreadable": "UNREADABLE",
}


def probe_config(cfg: dict[str, Any], check_network: bool, check_ssh: bool = False) -> dict[str, Any]:
    execu = cfg.get("execution") or {}
    card: dict[str, Any] = {
        "execution": {
            "host": execu.get("host"),
            "access": execu.get("access"),
            "allow_local_execution": execu.get("allow_local_execution", "unknown"),
            "workdir": probe_path("dir", execu.get("workdir")) if execu.get("workdir") else {"status": "not_provided"},
            "cpu_cores": execu.get("cpu_cores"),
            "memory_gb": execu.get("memory_gb"),
            "gpu": execu.get("gpu"),
            "scheduler": execu.get("scheduler"),
            "shared_machine": execu.get("shared_machine", "unknown"),
        },
        "tools": {},
        "databases": {},
        "data": {},
        "constraints": {},
    }
    for name, _, _ in TOOLS:
        card["tools"][name] = probe_tool(name, (cfg.get("tools") or {}).get(name))

    card["decisions"] = {
        name: check_decision(name, (cfg.get("decisions") or {}).get(name))
        for name in DECISIONS
    }

    db_map = {
        "BAKTA_DB_FULL": "dir",
        "BAKTA_DB_LIGHT": "dir",
        "AFDB_DIR": "dir",
        "PDB_MIRROR": "dir",
        "UNIPROT_FASTA": "file",
        "DEER_CKPT": "dir_or_file",
        "FEDKEA_HOME": "dir",
        "GMPS_ROOT": "dir",
        "GMPS_ANNOTATION": "file",
        "GMPS_SPECIES_MAP": "file",
    }
    for name, _label in DATABASES:
        value = (cfg.get("databases") or {}).get(name)
        card["databases"][name] = probe_path(db_map[name], value)

    for key in (
        "candidate_proteome_fasta",
        "candidate_genome_fasta",
        "candidate_annotation_gbff",
    ):
        card["data"][key] = probe_path("file", (cfg.get("data") or {}).get(key))
    for key in ("candidate_structure_dir",):
        card["data"][key] = probe_path("dir", (cfg.get("data") or {}).get(key))
    card["data"]["target_structure"] = probe_path("file", (cfg.get("data") or {}).get("target_structure"))

    host = (execu.get("host") or "").strip()
    access = (execu.get("access") or "").strip().lower()
    if check_ssh and host and access == "ssh":
        card["execution"]["ssh"] = probe_ssh(
            host,
            port=int(execu.get("ssh_port") or 22),
            user=execu.get("user"),
            run_command=True,
        )

    constraints = cfg.get("constraints") or {}
    card["constraints"] = {
        "network": constraints.get("network", "unknown"),
        "disk_quota": constraints.get("disk_quota"),
        "job_time_limit": constraints.get("job_time_limit"),
    }
    if check_network:
        hosts = constraints.get("network_hosts") or [
            "https://eutils.ncbi.nlm.nih.gov",
            "https://www.rcsb.org",
            "https://huggingface.co",
        ]
        card["constraints"]["network_probes"] = [probe_network(h) for h in hosts]
    return card


def render_report(card: dict[str, Any]) -> str:
    execu = card["execution"]
    lines = ["# 执行环境核查 / Environment check", ""]
    allow = execu.get("allow_local_execution")
    if allow is True:
        lines.append("**执行许可：允许在本机直接运行脚本。**")
    elif allow is False:
        lines.append("**执行许可：不允许本机执行——只给命令，由用户运行并交回结果。**")
    else:
        lines.append("**执行许可：未确认。在用户明确回答之前，不要在本机执行任何工具。**")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("| --- | --- |")
    for key in ("host", "access", "cpu_cores", "memory_gb", "gpu", "scheduler", "shared_machine"):
        value = execu.get(key)
        lines.append(f"| {key} | {value if value not in (None, '') else '—'} |")
    ssh = execu.get("ssh")
    if ssh:
        state = "可达" if ssh.get("reachable") else "不可达"
        lines.append("")
        lines.append(f"**远程执行主机：{state}。** {ssh.get('detail', '')}")
        lines.append("")
    decisions = card.get("decisions") or {}
    if decisions:
        lines.append("## 两个数据选择题")
        lines.append("")
        lines.append("| 问题 | 选择 | 状态 |")
        lines.append("| --- | --- | --- |")
        labels = {
            "candidate_data": "候选数据从哪来",
            "candidate_structures": "有没有候选结构",
        }
        for name, info in decisions.items():
            lines.append(f"| {labels.get(name, name)} | {info.get('choice') or '—'} | {info['status']} |")
        lines.append("")
        for name, info in decisions.items():
            if info["status"] != "resolved":
                lines.append(f"- **{labels.get(name, name)}**: {info['detail']}")
        lines.append("")

    wd = execu.get("workdir") or {}
    lines.append(f"| workdir | {wd.get('path') or '—'} ({STATUS_LABEL.get(wd.get('status'), wd.get('status'))}) |")
    lines.append("")

    lines.append("## 外部软件")
    lines.append("")
    lines.append("| 工具 | 用途 | 状态 | 版本 / 原因 |")
    lines.append("| --- | --- | --- | --- |")
    for name, label, purpose in TOOLS:
        info = card["tools"][name]
        status = STATUS_LABEL.get(info.get("status"), info.get("status"))
        detail = info.get("version") or info.get("detail") or ""
        missing_env = info.get("env_paths_missing") or []
        if missing_env and "环境变量路径不存在" not in detail:
            detail += f"（环境变量路径不存在: {', '.join(missing_env)}）"
        lines.append(f"| {label} | {purpose} | {status} | {detail} |")
    lines.append("")

    lines.append("## 数据库与数据")
    lines.append("")
    lines.append("| 项 | 状态 | 路径 / 说明 |")
    lines.append("| --- | --- | --- |")
    for name, label in DATABASES:
        info = card["databases"][name]
        extra = info.get("path") or ""
        if info.get("entries") is not None:
            extra += f"（{info['entries']} 项）"
        lines.append(f"| {label} | {STATUS_LABEL.get(info.get('status'), info.get('status'))} | {extra} |")
    for key, info in card["data"].items():
        lines.append(f"| {key} | {STATUS_LABEL.get(info.get('status'), info.get('status'))} | {info.get('path') or ''} |")
    lines.append("")

    unverified = [n for n, i in card["tools"].items() if i.get("status") == "unverified"]
    missing = [n for n, i in card["tools"].items() if i.get("status") == "missing"]
    lines.append("## 结论")
    lines.append("")
    if missing:
        lines.append(f"- **不可用（声明了但找不到）**：{', '.join(missing)}。这些工具对应的步骤只能给命令，或请用户修正路径。")
    if unverified:
        lines.append(
            f"- **未能验证（能运行但报不出版本）**：{', '.join(unverified)}。"
            "不要把“路径存在”当成“可以跑”；先让用户确认能正常执行，或用最小样例试跑一次。"
        )
    if not missing and not unverified:
        lines.append("- 用户声明的工具全部验证通过。")
    if allow is not True:
        lines.append("- 在执行许可明确之前，任何工具都不应被运行；先产出命令清单。")
    probes = card["constraints"].get("network_probes")
    if probes:
        lines.append("")
        lines.append("### 网络可达性")
        lines.append("")
        lines.append("| 目标 | 结果 |")
        lines.append("| --- | --- |")
        for probe in probes:
            state = "可达" if probe.get("reachable") else f"不可达（{probe.get('detail', '')}）"
            lines.append(f"| {probe['host']}:{probe.get('port')} | {state} |")
        lines.append("")
        lines.append("不可达时：不要调用任何会自动下载的流程（例如需要从 Hugging Face 取 checkpoint 的结构检索工具），先确认离线方案。")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# project config fragment
# ---------------------------------------------------------------------------

# Only tools the bundled runners actually read get a config block. Anything else is
# reported as a note rather than invented into the schema.
CONFIG_TOOL_KEYS = {
    "diamond": "sequence_screen",
    "cd-hit": "sequence_screen.cdhit_executable",
    "usalign": "usalign",
    "deer": "deer",
    "fedkea": "fedkea",
    "bakta": "genome_dataset.annotation",
    "signalp": "signalp",
    "esmfold": "structure_prediction",
}


def emit_project_config(card: dict[str, Any], source: Path) -> dict[str, Any]:
    """Translate a verified environment card into project.json's tools/inputs blocks.

    The rule that makes this worth doing is the same one the probe enforces: a path is
    written only for a tool that came back `ready`. Unverified or missing tools get an
    empty executable and `enabled: false`, so a project config can never claim a
    capability the environment check did not confirm.
    """
    allow = card["execution"].get("allow_local_execution") is True
    tools = card["tools"]
    dbs = card["databases"]
    data = card["data"]
    notes: list[str] = []

    def ready(name: str) -> tuple[bool, str]:
        info = tools.get(name) or {}
        if info.get("status") == "ready":
            return True, info.get("resolved") or info.get("declared") or ""
        return False, ""

    def block(name: str, extra: dict[str, Any] | None = None, label: str | None = None) -> dict[str, Any]:
        ok, path = ready(name)
        if not ok:
            status = (tools.get(name) or {}).get("status", "not_provided")
            if status != "not_provided":
                notes.append(f"{name}: {status} —— 未写入路径，enabled=false")
        out: dict[str, Any] = {
            "name": label or name,
            "enabled": ok,
            "auto_run_local": bool(ok and allow),
            "executable": path,
        }
        if extra:
            out.update(extra)
        return out

    cfg_tools: dict[str, Any] = {}

    dm_ok, dm_path = ready("diamond")
    cd_ok, cd_path = ready("cd-hit")
    seq = {
        "name": "DIAMOND",
        "enabled": bool(dm_ok and cd_ok),
        "auto_run_local": bool(dm_ok and cd_ok and allow),
        "executable": dm_path,
        "cdhit_executable": cd_path,
        "db": (data.get("candidate_proteome_fasta") or {}).get("path", "") or "",
    }
    if not cd_ok:
        notes.append(
            "sequence_screen: CD-HIT 未就绪，DIAMOND 单独可用也不能跑默认流程（去冗余是强制步骤）"
        )
    cfg_tools["sequence_screen"] = seq

    cfg_tools["structure_prediction"] = block("esmfold", label="ESMFold")
    cfg_tools["usalign"] = block("usalign", label="US-align")

    deer_ok, deer_path = ready("deer")
    deer_block = {
        "name": "DEER",
        "enabled": deer_ok,
        "auto_run_local": bool(deer_ok and allow),
        "executable": "python" if deer_path else "",
        "script_path": deer_path if deer_path.endswith(".py") else "",
        "user_supplied_path": deer_path,
        "ckpt_dir": (dbs.get("DEER_CKPT") or {}).get("path", "") or "",
        "output_dir": "outputs/alignments/deer",
    }
    if deer_ok and not deer_path.endswith(".py"):
        notes.append(
            "deer: 填入的是可执行文件路径，config 期望 script_path 指向 do_retrieval.py —— 请补上脚本路径"
        )
    cfg_tools["deer"] = deer_block

    fed_ok, fed_path = ready("fedkea")
    fed_info = tools.get("fedkea") or {}
    cfg_tools["fedkea"] = {
        "name": "FedKEA",
        "enabled": fed_ok,
        "auto_run_local": bool(fed_ok and allow),
        "executable": "python" if fed_path else "",
        "script_path": fed_path if fed_path.endswith(".py") else "",
        "user_supplied_path": fed_path,
        "env": fed_info.get("env") or {},
        "data_dir": (dbs.get("FEDKEA_HOME") or {}).get("path", "") or "",
        "local_result_dir": "outputs/fedkea/result",
    }
    if fed_info.get("env_paths_missing"):
        notes.append(
            "fedkea: 声明的环境变量路径不存在（"
            + ", ".join(fed_info["env_paths_missing"])
            + "）—— 运行前必须修正"
        )

    bakta_ok, bakta_path = ready("bakta")
    full_db = dbs.get("BAKTA_DB_FULL") or {}
    light_db = dbs.get("BAKTA_DB_LIGHT") or {}
    if full_db.get("status") == "ready":
        bakta_db, bakta_db_path = "full", full_db.get("path", "")
    elif light_db.get("status") == "ready":
        bakta_db, bakta_db_path = "light", light_db.get("path", "")
    else:
        bakta_db, bakta_db_path = "full", ""
        if bakta_ok:
            notes.append("bakta: 可执行文件就绪但没有数据库，注释无法启动")
        elif bakta_db_path:
            notes.append("bakta: 数据库已就绪，但可执行文件缺失或未验证 —— 注释仍无法启动")
    cfg_tools["genome_dataset"] = {
        "annotation": {
            "enabled": bool(bakta_ok and bakta_db_path),
            "auto_run_local": bool(bakta_ok and bakta_db_path and allow),
            "executable": bakta_path,
            "db": bakta_db,
            "db_path": bakta_db_path,
        }
    }

    cfg_tools["signalp"] = block("signalp", {"env": (tools.get("signalp") or {}).get("env") or {}}, label="SignalP")

    for name in ("hmmsearch", "esmfold"):
        if (tools.get(name) or {}).get("status") == "ready" and name not in CONFIG_TOOL_KEYS_CONSUMED:
            notes.append(f"{name}: 已确认可用，但插件当前的 runner 不读取它 —— 用它时需要自己给命令")

    cfg_inputs = {
        "target_structure_pdb": (data.get("target_structure") or {}).get("path", "") or "",
        "candidate_proteome_fasta": (data.get("candidate_proteome_fasta") or {}).get("path", "") or "",
        "candidate_genome_fasta": (data.get("candidate_genome_fasta") or {}).get("path", "") or "",
        "candidate_annotation_gbff": (data.get("candidate_annotation_gbff") or {}).get("path", "") or "",
        "candidate_structure_dir": (data.get("candidate_structure_dir") or {}).get("path", "") or "",
    }

    return {
        "_generated_by": "scripts/intake_environment.py --emit-config",
        "_source_environment": str(source),
        "_rule": "只写入 probe 结果为 ready 的路径；unverified/missing 一律留空并 enabled=false",
        "_notes": notes,
        "tools": cfg_tools,
        "inputs": cfg_inputs,
    }


CONFIG_TOOL_KEYS_CONSUMED = {"diamond", "cd-hit", "usalign", "deer", "fedkea", "bakta", "signalp"}


# ---------------------------------------------------------------------------
# path-leak audit: the repo must never carry one user's real paths
# ---------------------------------------------------------------------------

AUDIT_PATTERNS = [
    (re.compile(r"/Users/[A-Za-z0-9._-]+/"), "个人 macOS 主目录"),
    (re.compile(r"/home/(?!you/|user/|<)[A-Za-z0-9._-]+/"), "他人 Linux 主目录"),
    (re.compile(r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"), "私有网段地址"),
]
AUDIT_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "dist", "runs"}
AUDIT_SUFFIXES = {".md", ".json", ".py", ".sh", ".tsv", ".yml", ".yaml", ".txt", ".js"}


def audit_paths(root: Path) -> list[tuple[str, int, str, str]]:
    """Return (relative path, line, matched text, reason) for real paths in the tree."""
    findings: list[tuple[str, int, str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in AUDIT_SUFFIXES:
            continue
        if any(part in AUDIT_SKIP_DIRS for part in path.parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, 1):
            for pattern, reason in AUDIT_PATTERNS:
                match = pattern.search(line)
                if match:
                    findings.append((str(path.relative_to(root)), lineno, match.group(0), reason))
                    break
    return findings


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ask for and verify the execution environment before running workflows.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--ask", action="store_true", help="Print the questionnaire to send to the user.")
    parser.add_argument(
        "--task",
        choices=sorted(TASK_PROFILES),
        default=None,
        help="With --ask: scope the questionnaire to what this task needs (card / screening / structure / full).",
    )
    mode.add_argument("--init", action="store_true", help="Write an environment.json skeleton.")
    mode.add_argument("--probe", action="store_true", help="Verify the environment described by --config.")
    mode.add_argument(
        "--audit-paths",
        nargs="?",
        const=".",
        metavar="DIR",
        help="Fail if DIR (default: cwd) contains a real home directory or private IP address.",
    )
    parser.add_argument("--config", type=Path, default=None, help="environment.json for --probe.")
    parser.add_argument("--output", type=Path, default=None, help="Where --init writes the skeleton.")
    parser.add_argument("--output-card", type=Path, default=None, help="Where --probe writes environment_card.json.")
    parser.add_argument("--output-report", type=Path, default=None, help="Where --probe writes environment_report.md.")
    parser.add_argument("--check-network", action="store_true", help="Also probe network reachability (off by default).")
    parser.add_argument(
        "--check-ssh",
        action="store_true",
        help="When execution.access is 'ssh', test that the host is reachable and that BatchMode ssh works.",
    )
    parser.add_argument(
        "--emit-config",
        type=Path,
        default=None,
        help="With --probe: also write a project-config fragment (tools + inputs) using only ready tools.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.ask:
        if args.task is None:
            print(QUESTIONNAIRE)
            print()
            print("（以上是完整问卷。先确定目标再问环境可以更省事：")
            print("  --task card / screening / structure / full）")
            return 0
        profile = TASK_PROFILES[args.task]  # argparse restricts --task to these keys
        print(f"本次任务范围：{profile['label']}")
        print(f"说明：{profile['note']}")
        print()
        for group in profile["groups"]:
            print(GROUP_TEXT[group])
            print()
        # never skipped, whatever the scope: the judgment points come first
        print("先回答这些判断题（插件不会替你选）：")
        for number, name in enumerate(DECISIONS, 1):
            print(decision_question_text(name, number))
            print()
        # never skipped, whatever the scope: this is the one answer that gates execution
        print(PERMISSION_QUESTION)
        print()
        skipped = [g for g in GROUP_TEXT if g not in profile["groups"]]
        if skipped:
            print("这次不需要问：" + "、".join(GROUP_LABEL[g] for g in skipped))
            print("（真要用到时再补问；不要预先索取用不上的路径。）")
        return 0

    if args.audit_paths is not None:
        root = Path(args.audit_paths).resolve()
        findings = audit_paths(root)
        if not findings:
            print(f"路径审计通过：{root} 里没有他人主目录或私有网段地址。")
            return 0
        print(f"路径审计失败：{len(findings)} 处疑似真实路径（插件不能携带任何人的本地路径）", file=sys.stderr)
        for rel, lineno, text, reason in findings[:40]:
            print(f"  {rel}:{lineno}  {text}  ← {reason}", file=sys.stderr)
        if len(findings) > 40:
            print(f"  ... 还有 {len(findings) - 40} 处", file=sys.stderr)
        print(
            "\n改成占位符（/path/to/...）或让用户用 --init 生成自己的 environment.json；"
            "环境文件本身不要提交。",
            file=sys.stderr,
        )
        return 1

    if args.init:
        out = args.output or Path("environment.json")
        if out.exists():
            print(f"error: {out} already exists; move it aside first", file=sys.stderr)
            return 2
        out.write_text(json.dumps(skeleton(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out}")
        print("先让用户逐项填写；不确定的保留 null。然后运行：")
        print(f"  python3 scripts/intake_environment.py --probe --config {out} "
              "--output-card environment_card.json --output-report environment_report.md")
        return 0

    if args.config is None:
        print("error: --probe needs --config environment.json", file=sys.stderr)
        return 2
    if not args.config.is_file():
        print(f"error: config not found: {args.config}", file=sys.stderr)
        return 2
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    card = probe_config(cfg, args.check_network, args.check_ssh)
    report = render_report(card)

    if args.output_card:
        args.output_card.parent.mkdir(parents=True, exist_ok=True)
        args.output_card.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.output_card}")
    if args.output_report:
        args.output_report.parent.mkdir(parents=True, exist_ok=True)
        args.output_report.write_text(report, encoding="utf-8")
        print(f"wrote {args.output_report}")
    if not args.output_card and not args.output_report and not args.emit_config:
        print(report)

    if args.emit_config:
        fragment = emit_project_config(card, args.config)
        args.emit_config.parent.mkdir(parents=True, exist_ok=True)
        args.emit_config.write_text(json.dumps(fragment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.emit_config}")
        print("把这个文件的 tools / inputs 合并进 project.json；未就绪的工具已留空并 enabled=false。")
        for note in fragment["_notes"]:
            print(f"  note: {note}")

    blocked = [n for n, i in card["tools"].items() if i.get("status") in {"missing", "unverified"}]
    if card["execution"].get("allow_local_execution") is not True:
        print("注意：执行许可未确认为 true，不应在本机运行任何工具。", file=sys.stderr)
    if blocked:
        print(f"注意：以下工具不可用或未验证: {', '.join(blocked)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
