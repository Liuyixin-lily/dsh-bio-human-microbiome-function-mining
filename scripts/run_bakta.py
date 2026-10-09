#!/usr/bin/env python3
"""Run configured Bakta genome annotation through the bundled genome-annotation helper.

This wrapper follows the genome-annotation skill flow. It validates
BAKTA_BIN_DIR and the Bakta database, calls bakta_batch.sh when the environment
is accessible, and otherwise writes a pending checkpoint with the exact command
for the user to run on their own compute.
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


SKILL_SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "genome-annotation" / "scripts" / "bakta_batch.sh"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Bakta batch annotation and record provenance.")
    parser.add_argument("--project", type=Path, help="Path to a project.json/project folder.")
    parser.add_argument("--indir", type=Path, help="Directory of genome FASTA files.")
    parser.add_argument("--outdir", type=Path, help="Output root directory for Bakta results.")
    parser.add_argument("--db", choices=["full", "light"], help="Bakta database selection, default full.")
    parser.add_argument("--db-path", type=Path, help="Direct Bakta database path.")
    parser.add_argument("--threads", type=int, help="Bakta threads per genome.")
    parser.add_argument("--mode", choices=["ser", "par"], help="serial or parallel batch mode.")
    parser.add_argument("--par-jobs", type=int, help="Concurrent Bakta jobs in par mode.")
    parser.add_argument("--prefix-tag", help="Locus-tag prefix, default GENOME.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing genome output directories.")
    parser.add_argument("--log", type=Path, help="Log file path.")
    parser.add_argument("--executable", help="Path to the bakta executable.")
    parser.add_argument("--auto-run", dest="auto_run", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--checkpoint", type=Path, help="Checkpoint JSON path.")
    return parser.parse_args(argv)


def load_project(args: argparse.Namespace) -> tuple[dict[str, Any], Path]:
    if args.project is None:
        return {}, Path.cwd()
    project_path = args.project
    if project_path.is_dir():
        project_path = project_path / "project.json"
    if not project_path.is_file():
        print(f"project file not found: {args.project}", file=sys.stderr)
        return {}, Path.cwd()
    try:
        data = json.loads(project_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"failed to read project JSON: {exc}", file=sys.stderr)
        return {}, project_path.parent
    return data, project_path.parent


def resolve(path: Path, root: Path) -> Path:
    if path is None:
        return Path()
    return path if path.is_absolute() else (root / path)


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
        "next": "run the command above on compute with Bakta installed, then re-run this wrapper to parse output",
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def env_ready(args: argparse.Namespace) -> tuple[bool, str]:
    exe = args.executable or ""
    if exe:
        path = Path(resolve(Path(exe), Path.cwd()))
        if path.is_file() and os.access(path, os.X_OK):
            return True, str(path.parent)
        if "/" in exe or "\\" in exe:
            return False, f"Bakta executable not found: {exe}"
    if os.environ.get("BAKTA_BIN_DIR"):
        bin_dir = Path(os.environ["BAKTA_BIN_DIR"])
        if (bin_dir / "bakta").is_file() and os.access(bin_dir / "bakta", os.X_OK):
            return True, str(bin_dir)
    found = shutil.which("bakta")
    if found:
        return True, str(Path(found).parent)
    return False, "BAKTA_BIN_DIR not set or 'bakta' not found on PATH"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project, root = load_project(args)
    genome_cfg = project.get("genome_dataset") or {}
    ann_cfg = genome_cfg.get("annotation") or {}
    out_cfg = project.get("output") or {}

    indir = args.indir or Path(genome_cfg.get("download_output_dir", "databases/genomes"))
    outdir = args.outdir or Path(ann_cfg.get("output_dir", "outputs/annotations/bakta"))
    db = args.db or str(ann_cfg.get("db", "full"))
    db_path = args.db_path or Path(ann_cfg.get("db_path", ""))
    threads = args.threads if args.threads is not None else int(ann_cfg.get("threads", 8))
    mode = args.mode or "ser"
    par_jobs = args.par_jobs if args.par_jobs is not None else 3
    prefix_tag = args.prefix_tag or str(ann_cfg.get("prefix_tag", "GENOME"))
    force = args.force or bool(ann_cfg.get("force", False))
    log = args.log or Path("outputs/annotations/bakta/bakta_batch.log")
    executable = args.executable or str(ann_cfg.get("executable", ""))
    auto_run = args.auto_run if args.auto_run is not None else bool(genome_cfg.get("auto_run_local", True))
    checkpoint = args.checkpoint or Path(out_cfg.get("task_output_dir", "outputs/task")) / "state" / "checkpoint.json"

    indir = resolve(indir, root)
    outdir = resolve(outdir, root)
    db_path = resolve(db_path, root)
    log = resolve(log, root)
    checkpoint = resolve(checkpoint, root)

    if not indir.is_dir():
        print(f"genome input directory missing: {indir}", file=sys.stderr)
        return 1
    if not db_path and not os.environ.get("BAKTA_DB_FULL") and not os.environ.get("BAKTA_DB_LIGHT"):
        print("Bakta database not configured. Use --db-path or set BAKTA_DB_FULL/BAKTA_DB_LIGHT.", file=sys.stderr)
        return 489
    if not SKILL_SCRIPT.is_file():
        print(f"genome-annotation helper not found: {SKILL_SCRIPT}", file=sys.stderr)
        return 1

    cmd = ["bash", str(SKILL_SCRIPT), "--indir", str(indir), "--outdir", str(outdir), "--db", db]
    if db_path:
        cmd += ["--db-path", str(db_path)]
    cmd += ["--threads", str(threads), "--mode", mode, "--par-jobs", str(par_jobs), "--prefix-tag", prefix_tag]
    if force:
        cmd += ["--force"]
    cmd += ["--log", str(log)]

    ok, bin_dir = env_ready(args)
    if not auto_run or not ok:
        write_checkpoint(checkpoint, "pending", "bakta", cmd, [], bin_dir)
        print("Bakta not run locally. Provide the pending checkpoint command to the user or run it with --auto-run on compute.")
        print("REQUIRED_COMMAND")
        print(collection_cmd(cmd))
        return 9640

    env = os.environ.copy()
    env["BAKTA_BIN_DIR"] = bin_dir
    print(collection_cmd(cmd))
    result = subprocess.run(cmd, cwd=str(root), env=env)
    if result.returncode != 0:
        write_checkpoint(checkpoint, "failed", "bakta", cmd, [], f"exit={result.returncode}")
        return result.returncode

    write_checkpoint(
        checkpoint,
        "completed",
        "bakta",
        cmd,
        [str(outdir)],
    )
    print("Bakta annotation completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
