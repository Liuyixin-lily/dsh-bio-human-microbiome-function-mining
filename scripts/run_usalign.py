#!/usr/bin/env python3
"""Run configured US-align screening and parse output into plugin structure tables.

The command runs a pairwise US-align invocation for every PDB/CIF file in the
candidate directory. If the executable or inputs are not accessible from the
current terminal, it writes a pending checkpoint instead of fabricating
structural evidence.
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
        description="Run US-align structure screening and parse output into plugin TSVs."
    )
    parser.add_argument("--project", type=Path, help="Path to a project.json/project folder.")
    parser.add_argument("--target", type=Path, help="Reference target structure PDB/CIF.")
    parser.add_argument("--candidate-dir", type=Path, help="Directory of candidate structures.")
    parser.add_argument("--outdir", type=Path, help="Output directory for structural hits.")
    parser.add_argument("--threshold", type=float, help="TM-score threshold, default 0.5.")
    parser.add_argument("--candidate-id", help="Candidate id used in parsed rows, default 'candidate'.")
    parser.add_argument("--template-id", help="Fallback template id when not detected, default 'template'.")
    parser.add_argument("--plddt-mean", help="Mean pLDDT when known.")
    parser.add_argument("--tool-version", help="US-align version string.")
    parser.add_argument("--executable", help="Path or command for USalign, default from config or 'USalign'.")
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
    project_root = project_path if project_path.is_dir() else project_path.parent
    if project_path.is_dir():
        project_path = project_path / "project.json"
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
        "next": "run the command above on compute with US-align installed, then re-run this wrapper to parse output",
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def parse_usalign(args: argparse.Namespace, root: Path, outdir: Path, stdout_file: Path, candidate_source: Path,
                  out_hits: Path | None = None, out_candidates: Path | None = None) -> int:
    cmd = [
        sys.executable,
        str(Path(__file__).with_name("parse_usalign.py")),
        "--input",
        str(stdout_file),
        "--out-hits",
        str(out_hits or (outdir / "structural_hits.tsv")),
        "--out-candidates",
        str(out_candidates or (outdir / "structural_candidates.tsv")),
    ]
    if args.candidate_id:
        cmd += ["--candidate-id", str(args.candidate_id)]
    if args.template_id:
        cmd += ["--template-id", str(args.template_id)]
    if args.plddt_mean:
        cmd += ["--plddt-mean", str(args.plddt_mean)]
    if args.tool_version:
        cmd += ["--tool-version", str(args.tool_version)]
    cmd += ["--prediction-pdb", str(candidate_source)]
    cmd += ["--threshold", str(args.threshold if args.threshold is not None else 0.5)]
    print(collection_cmd(cmd))
    return subprocess.run(cmd, cwd=str(root)).returncode


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project, root = load_project(args)
    ua_cfg = (project.get("tools") or {}).get("usalign") or {}
    inputs_cfg = project.get("inputs") or {}
    out_cfg = project.get("output") or {}

    primary_ref = read_primary_reference(root)
    primary_target = Path(primary_ref.get("structure_file", "")) if primary_ref.get("structure_file") else Path()
    target = args.target or primary_target or Path(inputs_cfg.get("target_structure_pdb", "inputs/target_structure.pdb"))
    candidate_dir = args.candidate_dir or Path()
    outdir = args.outdir or Path(ua_cfg.get("output_dir", "outputs/alignments/usalign"))
    threshold = args.threshold if args.threshold is not None else float(ua_cfg.get("tm_score_threshold", 0.498))
    executable = args.executable or str(ua_cfg.get("executable", "USalign"))
    auto_run = args.auto_run if args.auto_run is not None else bool(ua_cfg.get("auto_run_local", True))
    checkpoint = args.checkpoint or Path(out_cfg.get("task_output_dir", "outputs/task")) / "state" / "checkpoint.json"

    target = resolve(target, root)
    candidate_dir = resolve(candidate_dir, root)
    outdir = resolve(outdir, root)
    checkpoint = resolve(checkpoint, root)

    if not target.is_file():
        print(f"target structure missing: {target}", file=sys.stderr)
        return 1
    if not candidate_dir.is_dir():
        print(f"candidate directory missing: {candidate_dir}", file=sys.stderr)
        return 489

    exe = executable_path(executable, root)
    outdir.mkdir(parents=True, exist_ok=True)
    structure_files = sorted(
        path
        for path in candidate_dir.iterdir()
        if path.is_file() and path.suffix.lower() in (".pdb", ".cif")
    )
    if not structure_files:
        print(f"no PDB/CIF files in candidate directory: {candidate_dir}", file=sys.stderr)
        return 489
    cmds_by_file = {
        path: [
            exe,
            str(target),
            str(path),
            "-outfmt",
            "2",
        ]
        for path in structure_files
    }

    representative_cmd = next(iter(cmds_by_file.values()))
    if not auto_run or not is_executable(exe, root):
        write_checkpoint(checkpoint, "pending", "usalign", representative_cmd, [], "tool/data not accessible or auto_run disabled")
        print("US-align not run locally. Provide the pending checkpoint command to the user or run it with --auto-run on compute.")
        print("REQUIRED_COMMAND")
        print(collection_cmd(representative_cmd))
        return 0

    outdir.mkdir(parents=True, exist_ok=True)
    temp_dir = outdir / ".usalign_parts"
    temp_dir.mkdir(parents=True, exist_ok=True)
    hit_parts = []
    cand_parts = []
    for struct in structure_files:
        name = struct.stem
        stdout_part = temp_dir / f"{name}.stdout.txt"
        hits_part = temp_dir / f"{name}.hits.tsv"
        cand_part = temp_dir / f"{name}.candidates.tsv"
        cmd = cmds_by_file[struct]
        print(collection_cmd(cmd))
        with stdout_part.open("w", encoding="utf-8") as stdout_handle:
            result = subprocess.run(cmd, stdout=stdout_handle, stderr=subprocess.PIPE, text=True, cwd=str(root))
        if result.returncode != 0:
            write_checkpoint(checkpoint, "failed", "usalign", cmd, [], result.stderr[-2000:])
            return result.returncode
        parsed = parse_usalign(args, root, temp_dir, stdout_part, struct, hits_part, cand_part)
        if parsed != 0:
            write_checkpoint(checkpoint, "failed", "usalign", cmd, [], "parse step failed")
            return parsed
        hit_parts.append(hits_part)
        cand_parts.append(cand_part)

    merge_partials(hit_parts, outdir / "structural_hits.tsv")
    merge_partials(cand_parts, outdir / "structural_candidates.tsv")
    shutil.rmtree(temp_dir, ignore_errors=True)

    write_checkpoint(
        checkpoint,
        "completed",
        "usalign",
        representative_cmd,
        [
            outdir / "structural_hits.tsv",
            outdir / "structural_candidates.tsv",
            outdir / "usalign_summary.txt",
        ],
    )
    write_summary(outdir, target, candidate_dir, threshold)
    print("US-align screening completed and parsed.")
    return 0


def merge_partials(parts: list[Path], output: Path) -> None:
    with output.open("w", encoding="utf-8") as handle:
        seen_header = False
        for part in parts:
            if not part.is_file():
                continue
            lines = part.read_text(encoding="utf-8").splitlines()
            if not lines:
                continue
            # Accept an existing header line from any part, and note the
            # parser always writes one, so this is mostly a safety net.
            if not seen_header and lines[0].startswith("#"):
                handle.write(lines[0] + "\n")
                seen_header = True
                lines = lines[1:]
            for line in lines:
                if line.strip():
                    handle.write(line + "\n")


def write_summary(
    outdir: Path,
    target: Path,
    candidate_dir: Path,
    threshold: float,
) -> None:
    lines = [
        "target                 " + str(target),
        "candidate_dir          " + str(candidate_dir),
        "structural_hits        " + str(outdir / "structural_hits.tsv"),
        "structural_candidates  " + str(outdir / "structural_candidates.tsv"),
        "tm_score_threshold     " + str(threshold),
        "deer_fallback          only if US-align finds no sufficient candidates",
    ]
    (outdir / "usalign_summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
