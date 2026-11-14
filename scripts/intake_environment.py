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

QUESTIONNAIRE = """\
在跑任何流程之前，请先回答下面 6 组问题。不知道的直接说“不知道”——我不会替你猜，
也不会假设某个软件已经装好。（回答后我会写进 environment.json 并逐项验证。）

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


def version_of(path: str, env: dict[str, str], timeout: int = 20) -> tuple[str | None, str]:
    """Try to get a version string. An empty answer means 'cannot verify', not 'ok'."""
    full_env = {**os.environ, **env}
    for flag in ("--version", "-version", "version"):
        try:
            proc = subprocess.run(
                [path, flag],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=full_env,
                cwd=os.path.expanduser("~"),
            )
        except FileNotFoundError:
            return None, "not found"
        except subprocess.TimeoutExpired:
            return None, f"timed out on `{flag}`"
        except PermissionError:
            return None, "not executable (permission denied)"
        except OSError as exc:
            return None, f"cannot run: {exc}"
        text = (proc.stdout or "") + (proc.stderr or "")
        line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        if line and any(ch.isdigit() for ch in line):
            return line, "ok"
        if line:
            # e.g. `echo --version` prints the flag back; that is not a version
            return None, f"输出不含版本号: {line[:60]!r}"
        if proc.returncode == 0:
            # ran cleanly but printed nothing usable
            return None, "ran but reported no version"
    return None, "no version flag produced output"


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
    version, why = version_of(resolved, env)
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


def probe_config(cfg: dict[str, Any], check_network: bool) -> dict[str, Any]:
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

    db_map = {
        "BAKTA_DB_FULL": "dir",
        "BAKTA_DB_LIGHT": "dir",
        "AFDB_DIR": "dir",
        "PDB_MIRROR": "dir",
        "UNIPROT_FASTA": "file",
        "DEER_CKPT": "file",
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
        "--emit-config",
        type=Path,
        default=None,
        help="With --probe: also write a project-config fragment (tools + inputs) using only ready tools.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.ask:
        print(QUESTIONNAIRE)
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
    card = probe_config(cfg, args.check_network)
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
