#!/usr/bin/env python3
"""Run CD-HIT plus configured DIAMOND sequence screening and parse the result.

This wrapper is derived from the sequence-mapping runner
(run_diamond_screening.sh) and the plugin's parse_sequence_hits.py. It checks
whether the configured executables and input files are accessible from the
current terminal, runs CD-HIT and DIAMOND when allowed, and otherwise writes a
pending checkpoint with the exact wrapper command the user should run later.

CD-HIT deduplication defaults to 100%% identity when each organism is
represented by a single genome, and 95%% identity when the candidate set
contains multiple genomes per organism (a pan-proteome). Set
`tools.sequence_screen.cdhit_identity` in project.json or pass
`--cluster-identity` to override this rule.
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
    parser = argparse.ArgumentParser(
        description="Run DIAMOND sequence screening and parse output into plugin TSVs."
    )
    parser.add_argument("--project", type=Path, help="Path to a project.json/project folder.")
    parser.add_argument("--query", type=Path, help="Target enzyme FASTA used as DIAMOND query.")
    parser.add_argument("--db", type=Path, help="Candidate proteome FASTA for makedb.")
    parser.add_argument("--dmnd", type=Path, help="Prebuilt DIAMOND database.")
    parser.add_argument("--cdhit", help="Path or command for cd-hit, default from config or 'cd-hit'.")
    parser.add_argument("--cluster-identity", type=float, help="CD-HIT cluster identity fraction for deduplication. Defaults to 1.0 for single-genome datasets and 0.95 for multi-genome pan-proteomes. Use 0 to skip CD-HIT.")
    parser.add_argument("--outdir", type=Path, help="Output directory for screening results.")
    parser.add_argument("--identity", type=float, help="Minimum percent identity, default 20.")
    parser.add_argument("--coverage", type=float, help="Minimum query coverage fraction, default 0.7.")
    parser.add_argument("--evalue", help="Maximum E-value, default 1e-5.")
    parser.add_argument("--threads", type=int, help="DIAMOND threads, default 8.")
    parser.add_argument("--max-target-seqs", type=int, help="Max alignments per query, default 50000.")
    parser.add_argument("--executable", help="Path or command for diamond, default from config or 'diamond'.")
    parser.add_argument("--auto-run", dest="auto_run", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--checkpoint", type=Path, help="Checkpoint JSON path.")
    return parser.parse_args(argv)


def read_primary_reference(root: Path) -> dict[str, Any]:
    """Read the primary reference record written by fetch_reference_enzymes.py."""
    candidates = [
        root / "outputs/task/reference_enzymes/primary_reference.json",
        root / "outputs/reference_enzymes/primary_reference.json",
        root / "reference_enzymes/primary_reference.json",
    ]
    for path in candidates:
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
    return {}


def load_project(args: argparse.Namespace) -> tuple[dict[str, Any], Path]:
    if args.project is None:
        return {}, Path.cwd()
    project_path = args.project
    if project_path.is_dir():
        project_root = project_path
        project_path = project_path / "project.json"
    else:
        # project.json files under a projects/ folder are still rooted one
        # level up, matching the README "cp ... project.json" layout.
        project_root = project_path.parent
        if project_path.parent.name == "projects":
            project_root = project_path.parent.parent
    if not project_path.is_file():
        print(f"project file not found: {args.project}", file=sys.stderr)
        return {}, project_root
    try:
        data = json.loads(project_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"failed to read project JSON: {exc}", file=sys.stderr)
        return {}, project_root
    return data, project_root


def resolve(path: Path, root: Path) -> Path:
    if path is None:
        return Path()
    return path if path.is_absolute() else (root / path)


def executable_path(value: str, root: Path) -> str:
    if "/" in value or "\\" in value:
        p = resolve(Path(value), root)
        return str(p) if Path(p).is_file() else value
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
        "next": "run the command above on compute with DIAMOND installed, then re-run this wrapper to parse output",
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def parse_filtered(args: argparse.Namespace, root: Path, outdir: Path, tool_version: str = "") -> int:
    filtered = outdir / "diamond_hits.filtered.tsv"
    parse_input = filtered
    if not parse_input.is_file() or parse_input.stat().st_size == 0:
        parse_input = outdir / "diamond_hits.tsv"
    if not parse_input.is_file() or parse_input.stat().st_size == 0:
        parse_input = outdir / "diamond_hits.m8"
    if not parse_input.is_file():
        print("no diamond hits TSV to parse", file=sys.stderr)
        return 1
    cmd = [
        sys.executable,
        str(Path(__file__).with_name("parse_sequence_hits.py")),
        "--input",
        str(parse_input),
        "--out-hits",
        str(outdir / "sequence_hits.tsv"),
        "--out-candidates",
        str(outdir / "sequence_candidates.tsv"),
        "--tool",
        "diamond",
    ]
    if tool_version:
        cmd += ["--tool-version", str(tool_version)]
    print(collection_cmd(cmd))
    return subprocess.run(cmd, cwd=str(root)).returncode


def default_cluster_identity(seq_cfg: dict[str, Any], project: dict[str, Any]) -> float:
    """Return effective CD-HIT identity, honoring config first then genome count."""
    configured = seq_cfg.get("cdhit_identity")
    if configured is not None:
        try:
            return float(configured)
        except (TypeError, ValueError):
            pass
    candidates = project.get("candidate_sequences") or {}
    genomes = candidates.get("genomes") or {}
    if len(genomes) > 1:
        return 0.95
    return 1.0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project, root = load_project(args)
    seq_cfg = (project.get("tools") or {}).get("sequence_screen") or {}
    inputs_cfg = project.get("inputs") or {}
    out_cfg = project.get("output") or {}

    primary_ref = read_primary_reference(root)
    primary_query = Path(primary_ref.get("sequence_file", "")) if primary_ref.get("sequence_file") else Path()
    query = args.query or primary_query or Path(inputs_cfg.get("target_sequence_fasta", "inputs/target_sequence.faa"))
    db = args.db or Path(seq_cfg.get("db", ""))
    dmnd = args.dmnd or (Path(seq_cfg["dmnd"]) if seq_cfg.get("dmnd") else None)
    outdir = args.outdir or Path(seq_cfg.get("output_dir", "outputs/sequence_screening"))
    identity = args.identity if args.identity is not None else float(seq_cfg.get("identity_threshold", 20))
    coverage = args.coverage if args.coverage is not None else float(seq_cfg.get("query_coverage_threshold", 0.7))
    evalue = args.evalue or str(seq_cfg.get("evalue_threshold", "1e-5"))
    threads = args.threads if args.threads is not None else int(seq_cfg.get("threads", 8))
    max_targets = args.max_target_seqs if args.max_target_seqs is not None else int(seq_cfg.get("max_target_seqs", 50000))
    executable = args.executable or str(seq_cfg.get("executable", "diamond"))
    cdhit = args.cdhit or str(seq_cfg.get("cdhit_executable", "cd-hit"))
    cluster_identity = args.cluster_identity if args.cluster_identity is not None else default_cluster_identity(seq_cfg, project)
    auto_run = args.auto_run if args.auto_run is not None else bool(seq_cfg.get("auto_run_local", True))
    checkpoint = args.checkpoint or Path(out_cfg.get("task_output_dir", "outputs/task")) / "state" / "checkpoint.json"

    query = resolve(query, root)
    db = resolve(db, root)
    if dmnd is not None:
        dmnd = resolve(dmnd, root)
    outdir = resolve(outdir, root)
    checkpoint = resolve(checkpoint, root)

    if not query.is_file():
        print(f"query FASTA missing: {query}", file=sys.stderr)
        return 1
    if (dmnd is None or not str(dmnd)) and not db:
        print("provide either --dmnd or a candidate proteome --db", file=sys.stderr)
        return 180

    exe = executable_path(executable, root)
    commands: list[list[str]] = []
    dmnd_used = dmnd if (dmnd is not None and str(dmnd)) else None
    makedb_needed = False
    dedup_db = db
    if (dmnd_used is None) and db:
        outdir.mkdir(parents=True, exist_ok=True)
        if cluster_identity > 0:
            clustered_faa = outdir / "candidate_proteome_cdhit100.faa"
            commands.append(
                [
                    executable_path(cdhit, root),
                    "-i",
                    str(db),
                    "-o",
                    str(clustered_faa),
                    "-c",
                    str(cluster_identity),
                    "-n",
                    "5",
                    "-M",
                    str(int(seq_cfg.get("memory_mb", 8000))),
                    "-T",
                    str(threads),
                    "-d",
                    "0",
                ]
            )
            dedup_db = clustered_faa
        dmnd_used = (outdir / "panproteome.dmnd").resolve()
        makedb_needed = True
    if makedb_needed:
        commands.append([exe, "makedb", "--in", str(dedup_db), "--db", str(dmnd_used), "--threads", str(threads)])
    outdir.mkdir(parents=True, exist_ok=True)
    commands.append(
        [
            exe,
            "blastp",
            "--query",
            str(query),
            "--db",
            str(dmnd_used),
            "--out",
            str(outdir / "diamond_hits.m8"),
            "--outfmt",
            "6",
            "qseqid",
            "sseqid",
            "pident",
            "length",
            "mismatch",
            "gapopen",
            "qstart",
            "qend",
            "sstart",
            "send",
            "evalue",
            "bitscore",
            "qcovhsp",
            "--evalue",
            str(evalue),
            "--threads",
            str(threads),
            "--max-target-seqs",
            str(max_targets),
        ]
    )
    if not auto_run or not is_executable(exe, root):
        cmd = next(c for c in commands)
        write_checkpoint(checkpoint, "pending", "diamond", cmd, [], "tool/data not accessible or auto_run disabled")
        print("DIAMOND not run locally. Provide the returned checkpoint command to the user or run it with --auto-run on compute.")
        print("REQUIRED_COMMAND")
        print(collection_cmd(commands[-1] if len(commands) == 1 else [sys.executable, str(Path(__file__))] + [str(a) for a in sys.argv[1:]]))
        return 0

    for cmd in commands:
        print(collection_cmd(cmd))
        result = subprocess.run(cmd, cwd=str(root))
        if result.returncode != 0:
            write_checkpoint(checkpoint, "failed", "diamond", cmd, [], f"exit={result.returncode}")
            return result.returncode

    parsed = parse_filtered(args, root, outdir)
    if parsed != 0:
        write_checkpoint(checkpoint, "failed", "diamond", commands[-1], [], "parse step failed")
        return parsed

    write_checkpoint(
        checkpoint,
        "completed",
        "diamond",
        commands[-1],
        [
            outdir / "diamond_hits.m8",
            outdir / "diamond_hits.tsv",
            outdir / "diamond_hits.filtered.tsv",
            outdir / "sequence_hits.tsv",
            outdir / "sequence_candidates.tsv",
        ],
    )
    print("DIAMOND screening completed and parsed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
