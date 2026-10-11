#!/usr/bin/env python3
"""Run a configured local SignalP prediction and parse its result files.

SignalP is not bundled with the plugin. This wrapper runs SignalP only when the
user provides an accessible executable and input FASTA and `auto_run_local` is
enabled. Otherwise it writes a pending checkpoint with the exact command and
consumes returned SignalP output.

Supported configurations under `tools.signalp`:

  "executable": path or command for SignalP 6 (or SignalP 5 compatible wrapper)
  "org": "gram-positive" | "gram-negative" | "eukarya" (SignalP 6)
  "format": "txt" (SignalP 6 default) or "short" (SignalP 5)
  "mode": "fast" (SignalP 6) or omit
  "prefix": output prefix basename, default "candidate_signalp"
  "output_dir": directory for raw SignalP outputs
  "env": dict of extra environment variables
  "auto_run_local": true/false
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SignalP and parse output into plugin TSVs.")
    parser.add_argument("--project", type=Path, help="Path to a project.json/project folder.")
    parser.add_argument("--query", type=Path, help="Candidate protein FASTA used as SignalP input.")
    parser.add_argument("--executable", help="Path or command for signalp6/signalp.")
    parser.add_argument("--org", help="SignalP organism group: gram-positive, gram-negative, eukarya.")
    parser.add_argument("--format", help="SignalP output format: txt or short.")
    parser.add_argument("--mode", help="SignalP 6 fast/slow mode.")
    parser.add_argument("--prefix", help="Output prefix basename.")
    parser.add_argument("--outdir", type=Path, help="Output directory for raw SignalP files.")
    parser.add_argument("--env-var", action="append", default=[], metavar="NAME=VALUE", help="Extra environment variable, repeatable.")
    parser.add_argument("--auto-run", dest="auto_run", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--checkpoint", type=Path, help="Checkpoint JSON path.")
    parser.add_argument("--tool-version", help="SignalP version or repository tag.")
    return parser.parse_args(argv)


def load_project(args: argparse.Namespace) -> tuple[dict[str, Any], Path]:
    if args.project is None:
        return {}, Path.cwd()
    project_path = args.project
    if project_path.is_dir():
        project_path = project_path / "project.json"
        root = args.project
    else:
        root = project_path.parent
    if not project_path.is_file():
        print(f"project file not found: {args.project}", file=sys.stderr)
        return {}, root
    try:
        data = json.loads(project_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"failed to read project JSON: {exc}", file=sys.stderr)
        return {}, root
    return data, root


def resolve(path: Path, root: Path) -> Path:
    if path is None:
        return Path()
    return path if path.is_absolute() else (root / path)


def executable_path(value: str, root: Path) -> str:
    if "/" in value or "\\" in value:
        p = resolve(Path(value), root)
        return str(p) if p.is_file() else value
    return value


def is_executable(value: str, root: Path) -> bool:
    if "/" in value or "\\" in value:
        p = resolve(Path(value), root)
        return p.is_file() and os.access(p, os.X_OK)
    return shutil.which(value) is not None


def collection_cmd(cmd: list[str]) -> str:
    return " ".join(str(part) for part in cmd)


def write_checkpoint(path: Path, status: str, step: str, command: list[str], outputs: list[str], error: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "step": step,
        "status": status,
        "command": collection_cmd(command),
        "outputs": [str(p) for p in outputs],
        "error": error,
        "next": "run the command above on compute with SignalP installed, then re-run this wrapper to parse output",
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def build_env(sig_cfg: dict[str, Any], extra: list[str]) -> dict[str, str]:
    env = os.environ.copy()
    overrides = dict(sig_cfg.get("env") or {})
    for item in extra:
        if "=" not in item:
            continue
        key, _, value = item.partition("=")
        if key:
            overrides[key] = value
    env.update(overrides)
    return env


def find_gff(outdir: Path, prefix: str) -> Path | None:
    candidates = [
        outdir / f"{prefix}.gff3",
        outdir / f"{prefix}.gff",
        outdir / "candidate_signalp.gff3",
        outdir / "candidate_signalp.gff",
    ]
    for path in candidates:
        if path.is_file():
            return path
    for path in sorted(outdir.glob("*.gff3")):
        return path
    for path in sorted(outdir.glob("*.gff")):
        return path
    return None


def build_command(
    executable: str,
    query: Path,
    org: str,
    format_name: str,
    mode: str | None,
    prefix: str,
    outdir: Path,
) -> list[str]:
    cmd = [executable, "-fasta", str(query)]
    if format_name:
        cmd += ["-format", format_name]
    if org:
        cmd += ["-org", org]
    if mode:
        cmd += ["-mode", mode]
    cmd += ["-prefix", str(outdir / prefix)]
    return cmd


def parse_signalp(root: Path, outdir: Path, tool_version: str, results_tsv: Path, query: Path) -> int:
    prefix_candidates = ["candidate_signalp", "signalp"]
    gff = None
    summary = None
    for prefix in prefix_candidates:
        gff = find_gff(outdir, prefix)
        if gff is None:
            continue
        summary_candidates = [
            outdir / f"{prefix}_summary.signalp5",
            outdir / f"{prefix}.summary",
            outdir / f"{prefix}.txt",
        ]
        for candidate in summary_candidates:
            if candidate.is_file():
                summary = candidate
                break
        break
    if gff is None:
        print(f"no SignalP GFF3 output found in {outdir}", file=sys.stderr)
        return 717
    cmd = [
        sys.executable,
        str(Path(__file__).with_name("parse_signalp.py")),
        "--gff3",
        str(gff),
        "--output",
        str(results_tsv),
        "--tool-version",
        tool_version,
    ]
    if summary is not None:
        cmd += ["--summary", str(summary)]
    print(collection_cmd(cmd))
    return subprocess.run(cmd, cwd=str(root)).returncode


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project, root = load_project(args)
    tools_cfg = project.get("tools") or {}
    sig_cfg = tools_cfg.get("signalp") or {}
    inputs_cfg = project.get("inputs") or {}
    out_cfg = project.get("output") or {}

    query = args.query or Path(inputs_cfg.get("candidate_proteome_fasta", "outputs/task/candidate_sequences/candidate_proteins.faa"))
    executable = args.executable or str(sig_cfg.get("executable", "signalp6"))
    org = args.org or str(sig_cfg.get("org", ""))
    format_name = args.format or str(sig_cfg.get("format", "txt"))
    mode = args.mode or (str(sig_cfg["mode"]) if sig_cfg.get("mode") else None)
    prefix = args.prefix or str(sig_cfg.get("prefix", "candidate_signalp"))
    outdir = args.outdir or Path(sig_cfg.get("output_dir", "outputs/signalp"))
    tool_version = args.tool_version or str(sig_cfg.get("tool_version", "SignalP"))
    auto_run = args.auto_run if args.auto_run is not None else bool(sig_cfg.get("auto_run_local", False))
    checkpoint = args.checkpoint or Path(out_cfg.get("task_output_dir", "outputs/task")) / "state" / "checkpoint.json"
    run_env = build_env(sig_cfg, args.env_var)

    query = resolve(query, root)
    outdir = resolve(outdir, root)
    checkpoint = resolve(checkpoint, root)

    if not query.is_file():
        print(f"candidate protein FASTA missing: {query}", file=sys.stderr)
        return 180

    exe = executable_path(executable, root)
    ok = is_executable(exe, root)
    if not ok:
        reason = f"SignalP executable not found: {exe}"
    else:
        reason = ""

    cmd = build_command(exe, query, org, format_name, mode, prefix, outdir)
    results_tsv = outdir / "candidate_signal_peptides.tsv"

    if not auto_run or not ok:
        write_checkpoint(checkpoint, "pending", "signalp", cmd, [str(results_tsv)], reason or "auto_run disabled")
        print("SignalP not run locally. Provide the returned checkpoint command to the user or run it with --auto-run on compute.")
        print("REQUIRED_COMMAND")
        print(collection_cmd(cmd))
        return 0

    outdir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(cmd, cwd=str(root), env=run_env)
    if proc.returncode != 0:
        write_checkpoint(checkpoint, "failed", "signalp", cmd, [], f"SignalP exited with code {proc.returncode}")
        print(f"SignalP command failed with code {proc.returncode}", file=sys.stderr)
        return proc.returncode

    write_checkpoint(checkpoint, "done", "signalp", cmd, [str(results_tsv)], "")
    return parse_signalp(root, outdir, tool_version, results_tsv, query)


if __name__ == "__main__":
    raise SystemExit(main())
