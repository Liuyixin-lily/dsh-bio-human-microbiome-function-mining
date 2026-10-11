#!/usr/bin/env python3
"""Run a configured local FEDKEA prediction and parse its result files.

The wrapper follows the FEDKEA GitHub workflow documented in
references/README.md. It checks whether the executable and FEDKEA main.py are
accessible from the current terminal, runs FEDKEA when allowed, and otherwise
writes a pending checkpoint with the exact command for the user to run on their
own server. The wrapper never calls the FEDKEA web server programmatically.
"""

from __future__ import annotations

import argparse
import os
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run FEDKEA enzyme/EC prediction and parse output.")
    parser.add_argument("--project", type=Path, help="Path to a project.json/project folder.")
    parser.add_argument("--query", type=Path, help="Candidate proteome FASTA used as -i.")
    parser.add_argument(
        "--expected-accessions",
        type=Path,
        help=(
            "Plain accession list or TSV/CSV with an ID column for the expected "
            "candidate IDs. Passed through to parse_fedkea.py so output "
            "accessions are checked for joinability back to the submitted "
            "candidate subset."
        ),
    )
    parser.add_argument("--outdir", type=Path, help="FEDKEA result output directory (-o).")
    parser.add_argument("--datadir", type=Path, help="FEDKEA model/data directory (-d).")
    parser.add_argument("--gpu", help="GPU ids as string, e.g. '0' or '0,1'; omit for CPU (-g).")
    parser.add_argument("--batch-size", type=int, help="FEDKEA batch size (-b), default 64.")
    parser.add_argument("--threshold", type=float, help="Enzyme/non-enzyme threshold (-t).")
    parser.add_argument("--executable", help="Executable used to run main.py, default python.")
    parser.add_argument("--script-path", type=Path, help="Path to FEDKEA main.py.")
    parser.add_argument("--tool-version", help="FEDKEA version or repository tag.")
    parser.add_argument("--env-var", action="append", default=[], metavar="NAME=VALUE", help="Extra environment variable for the FEDKEA subprocess, repeatable.")
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
        "next": "run the command above on compute with FEDKEA installed, or take the web route and save returned result files, then re-run this wrapper to parse output",
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def is_accessible(executable: str, script_path: Path, root: Path) -> tuple[bool, str]:
    resolved_script = resolve(script_path, root)
    if not resolved_script.is_file():
        return False, f"FEDKEA main.py not found: {resolved_script}"
    if not Path(executable).is_file() and shutil.which(executable) is None:
        return False, f"FEDKEA executable not found: {executable}"
    return True, ""


def build_command(
    executable: str,
    script_path: Path,
    query: Path,
    datadir: Path,
    outdir: Path,
    gpu: str | None,
    batch_size: int,
    threshold: float | None,
    root: Path,
) -> list[str]:
    script = resolve(script_path, root)
    cmd = [executable, str(script), "-i", str(query), "-b", str(batch_size), "-d", str(datadir), "-o", str(outdir)]
    if gpu is not None:
        cmd += ["-g", str(gpu)]
    if threshold is not None:
        cmd += ["-t", str(threshold)]
    return cmd


def parse_command(
    root: Path,
    outdir: Path,
    tool_version: str,
    results_tsv: Path,
    expected_accessions: Path | None = None,
) -> list[str]:
    """Build the post-FedKEA parse command as a list of CLI strings."""
    cmd = [
        sys.executable,
        str(Path(__file__).with_name("parse_fedkea.py")),
        "--output",
        str(results_tsv),
        "--tool-version",
        tool_version,
    ]
    if (outdir / "binary_result.txt").is_file():
        cmd += ["--binary-result", str(outdir / "binary_result.txt")]
    if (outdir / "enzyme_result_with_probability.csv").is_file():
        cmd += ["--probability-csv", str(outdir / "enzyme_result_with_probability.csv")]
    if (outdir / "enzyme_result_with_confidence.csv").is_file():
        cmd += ["--confidence-csv", str(outdir / "enzyme_result_with_confidence.csv")]
    if expected_accessions is not None:
        cmd += ["--expected-accessions", str(expected_accessions)]
    return cmd


def build_env(fed_cfg: dict[str, Any], extra: list[str]) -> dict[str, str]:
    """Return an environment dict for the FEDKEA subprocess.

    FEDKEA main.py internally calls ``python`` for helper subprocesses, and
    on some conda installs numpy/torch fail until ``LD_LIBRARY_PATH`` points at
    the conda environment lib directory. Config keys under
    ``validation_inputs.fedkea.env`` and CLI ``--env-var NAME=VALUE`` flags are
    merged with the current environment.
    """

    env = os.environ.copy()
    overrides: dict[str, str] = dict(fed_cfg.get("env") or {})
    for item in extra:
        if "=" not in item:
            continue
        key, _, value = item.partition("=")
        if key:
            overrides[key] = value
    env.update(overrides)
    return env


def parse_fedkea(
    root: Path,
    outdir: Path,
    required_files: list[str],
    tool_version: str,
    results_tsv: Path,
    expected_accessions: Path | None = None,
) -> int:
    binary = outdir / "binary_result.txt"
    probability = outdir / "enzyme_result_with_probability.csv"
    confidence = outdir / "enzyme_result_with_confidence.csv"
    missing = [name for name in required_files if not (outdir / name).is_file()]
    if missing:
        print(f"missing FEDKEA result files: {', '.join(missing)}", file=sys.stderr)
        return 2

    cmd = parse_command(root, outdir, tool_version, results_tsv, expected_accessions)
    print(collection_cmd(cmd))
    return subprocess.run(cmd, cwd=str(root)).returncode


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project, root = load_project(args)
    fed_cfg = (project.get("validation_inputs") or {}).get("fedkea") or {}
    out_cfg = project.get("output") or {}

    query = args.query or Path(fed_cfg.get("candidate_proteome", "outputs/sequence_screening/sequence_candidates.faa"))
    expected_accessions = args.expected_accessions or fed_cfg.get("expected_accessions")
    outdir = args.outdir or Path(fed_cfg.get("local_result_dir", "outputs/fedkea/result"))
    datadir = args.datadir or Path(fed_cfg.get("data_dir", fed_cfg.get("datadir", "data")))
    gpu = args.gpu if args.gpu is not None else fed_cfg.get("gpu")
    batch_size = args.batch_size if args.batch_size is not None else int(fed_cfg.get("batch_size", 64))
    threshold = args.threshold if args.threshold is not None else fed_cfg.get("threshold")
    executable = args.executable or str(fed_cfg.get("executable", "python"))
    script_path = args.script_path or Path(fed_cfg.get("script_path", "/path/to/FEDKEA/main.py"))
    tool_version = args.tool_version or str(fed_cfg.get("tool_version", "FEDKEA GitHub main"))
    required_files = list(fed_cfg.get("required_files", []))
    auto_run = args.auto_run if args.auto_run is not None else bool(fed_cfg.get("auto_run_local", True))
    checkpoint = args.checkpoint or Path(out_cfg.get("task_output_dir", "outputs/task")) / "state" / "checkpoint.json"
    run_env = build_env(fed_cfg, args.env_var)

    query = resolve(query, root)
    if expected_accessions is not None:
        expected_accessions = Path(expected_accessions)
        expected_accessions = resolve(expected_accessions, root)
    outdir = resolve(outdir, root)
    datadir = resolve(datadir, root)
    script_path = resolve(script_path, root)
    checkpoint = resolve(checkpoint, root)

    if not query.is_file():
        print(f"candidate proteome FASTA missing: {query}", file=sys.stderr)
        return 1
    if not required_files:
        required_files = [
            "binary_result.txt",
            "enzyme_result_with_probability.csv",
            "enzyme_result_with_confidence.csv",
        ]

    cmd = build_command(
        executable,
        script_path,
        query,
        datadir,
        outdir,
        gpu if isinstance(gpu, str) else (str(gpu) if gpu is not None else None),
        batch_size,
        float(threshold) if threshold not in (None, "") else None,
        root,
    )

    ok, reason = is_accessible(executable, script_path, root)
    if not auto_run or not ok:
        write_checkpoint(checkpoint, "pending", "fedkea", cmd, [], reason or "auto_run disabled")
        print("FEDKEA not run locally. Provide the returned checkpoint command to the user or run it with --auto-run on compute.")
        print("REQUIRED_COMMAND")
        print(collection_cmd(cmd))
        return 9640

    print(collection_cmd(cmd))
    result = subprocess.run(cmd, cwd=str(root), env=run_env)
    if result.returncode != 0:
        write_checkpoint(checkpoint, "failed", "fedkea", cmd, [], f"exit={result.returncode}")
        return result.returncode

    results_tsv = outdir.parent / "fedkea_results.tsv"
    parsed = parse_fedkea(
        root,
        outdir,
        required_files,
        tool_version,
        results_tsv,
        expected_accessions=expected_accessions,
    )
    if parsed != 0:
        write_checkpoint(checkpoint, "failed", "fedkea", cmd, [], "parse step failed")
        return parsed

    write_checkpoint(
        checkpoint,
        "completed",
        "fedkea",
        cmd,
        [
            outdir / "binary_result.txt",
            outdir / "enzyme_result_with_probability.csv",
            outdir / "enzyme_result_with_confidence.csv",
            results_tsv,
        ],
    )
    print("FEDKEA prediction completed and parsed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
