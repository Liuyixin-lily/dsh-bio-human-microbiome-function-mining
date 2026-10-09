#!/usr/bin/env python3
"""Run DEER retrieval as a fallback after US-align finds no candidates for a genome.

This wrapper follows the DEER command documented by the upstream repository:

  python do_retrieval.py --template_pdb_dir ... --database_pdb_dir ... --output_dir ...

DEER is additional structure-based evidence; it is never a replacement for
US-align. The wrapper only runs for source genomes where US-align produced no
structure-supported candidates. If US-align output is missing entirely, the
command still refuses unless the user explicitly passes
--allow-without-usalign.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run DEER structural retrieval after US-align.")
    parser.add_argument("--project", type=Path, help="Path to a project.json/project folder.")
    parser.add_argument("--template-dir", type=Path, help="Directory of reference/template structures.")
    parser.add_argument("--candidate-dir", type=Path, help="Directory of candidate structures.")
    parser.add_argument("--outdir", type=Path, help="DEER output directory.")
    parser.add_argument("--usalign-dir", type=Path, help="Existing US-align output directory.")
    parser.add_argument("--executable", help="Executable used to start do_retrieval.py, default python.")
    parser.add_argument("--script-path", type=Path, help="Path to DEER do_retrieval.py.")
    parser.add_argument("--tool-version", help="DEER version or repository tag.")
    parser.add_argument("--device", choices=["cpu", "gpu"], help="Force CPU or allow GPU execution.")
    parser.add_argument(
        "--allow-without-usalign",
        dest="allow_without_usalign",
        action="store_true",
        help="Explicitly override the DEER fallback gate.",
    )
    parser.add_argument(
        "--require-usalign",
        dest="allow_without_usalign",
        action="store_false",
        help="Require visible US-align output before running DEER (default).",
    )
    parser.set_defaults(allow_without_usalign=None)
    parser.add_argument("--auto-run", dest="auto_run", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--checkpoint", type=Path, help="Checkpoint JSON path.")
    parser.add_argument(
        "--ckpt-dir",
        type=Path,
        help="DEER model checkpoint directory (contains saprot_35m/, esm2_t12_35M_UR50D/, deer_checkpoint.ckpt).",
    )
    parser.add_argument(
        "--deer-model-path",
        type=Path,
        help="Path to deer_checkpoint.ckpt when it differs from ckpt_dir / deer_checkpoint.ckpt.",
    )
    parser.add_argument(
        "--skip-hf-checkpoint",
        dest="skip_hf_checkpoint",
        action="store_true",
        help="Set HF_HUB_OFFLINE=1 when local checkpoints are already prepared, avoiding network access to Hugging Face.",
    )
    parser.add_argument("--top-k", type=int, help="DEER retrieval top_k hits per template.")
    parser.add_argument("--tmp-dir", type=Path, help="DEER temporary directory for token cache.")
    parser.add_argument(
        "--distance-cutoff",
        type=float,
        help="Distance cutoff used by parse_deer.py to mark structure_support=1.",
    )
    return parser.parse_args(argv)


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


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def source_genome_for_candidate(candidate_id: str, project: dict[str, Any]) -> str:
    """Return the configured source genome for a candidate id when known."""
    candidates_cfg = (project.get("candidate_sequences") or {}).get("candidates") or {}
    if candidate_id in candidates_cfg:
        return str(candidates_cfg[candidate_id].get("source_genome", ""))
    return ""


def match_genome_from_columns(row: dict[str, str], source_genomes: list[str]) -> str:
    """Best-effort genome match from schema columns when candidate_id is unknown."""
    for name_col in ("organism_or_strain", "assembly_accession", "annotation"):
        value = str(row.get(name_col, "")).strip()
        if not value:
            continue
        for genome in source_genomes:
            if value == genome or value.startswith(genome):
                return genome
    return ""


def identify_genomes_without_candidates(
    project: dict[str, Any],
    usalign_dir: Path,
    candidate_dir: Path,
) -> tuple[list[str], list[str]]:
    """Return (missing_candidate_genomes, never_seen_genomes).

    A genome is considered structurally screened when a US-align hit maps to it
    through project candidate metadata or schema columns. A genome is missing a
    candidate when no US-align hit for that genome has structure_support=1.
    """
    source_genomes = configured_source_genomes(project)
    if not source_genomes:
        return [], []

    id_to_genome = build_id_to_genome(candidate_dir, source_genomes)
    id_to_genome.update(build_id_to_genome_from_project_candidates(project))

    hits = read_tsv(usalign_dir / "structural_hits.tsv")
    candidates = read_tsv(usalign_dir / "structural_candidates.tsv")
    if not hits and not candidates:
        return source_genomes, source_genomes

    supported_ids: set[str] = set()
    for row in candidates:
        if str(row.get("structure_support", "")).lower() in ("1", "true", "yes"):
            cid = str(row.get("candidate_id", "")).strip()
            if cid:
                supported_ids.add(cid)
    for row in hits:
        if str(row.get("structure_support", "")).lower() in ("1", "true", "yes"):
            cid = str(row.get("candidate_id", "")).strip()
            if cid:
                supported_ids.add(cid)

    genomes_with_candidate: set[str] = set()
    genomes_visible: set[str] = set()
    for row in hits:
        cid = str(row.get("candidate_id", "")).strip()
        genome = id_to_genome.get(cid, "") or source_genome_for_candidate(cid, project)
        if not genome:
            genome = match_genome_from_columns(row, source_genomes)
        if not genome:
            continue
        genomes_visible.add(genome)
        if cid in supported_ids or str(row.get("structure_support", "")).lower() in ("1", "true", "yes"):
            genomes_with_candidate.add(genome)

    missing = [genome for genome in source_genomes if genome not in genomes_with_candidate]
    never_seen = [genome for genome in source_genomes if genome not in genomes_visible]
    return missing, never_seen


def configured_source_genomes(project: dict[str, Any]) -> list[str]:
    candidate_seq = project.get("candidate_sequences") or {}
    genomes_cfg = candidate_seq.get("genomes") or {}
    genomes = {str(key) for key in genomes_cfg.keys()} - {""}
    candidates_cfg = candidate_seq.get("candidates") or {}
    genomes.update(
        str(item.get("source_genome", ""))
        for item in candidates_cfg.values()
        if item.get("source_genome")
    )
    return sorted(genomes)


def build_id_to_genome(candidate_dir: Path, source_genomes: list[str]) -> dict[str, str]:
    """Map structure id to source genome by reading symlinks in candidate_dir."""
    mapping: dict[str, str] = {}
    if not candidate_dir.is_dir():
        return mapping
    for path in candidate_dir.iterdir():
        if path.suffix.lower() not in (".pdb", ".cif"):
            continue
        try:
            target = Path(os.path.realpath(path))
        except OSError:
            continue
        parts = target.parts
        for genome in source_genomes:
            if any(part == genome or part.startswith(genome) for part in parts):
                mapping[path.stem] = genome
                break
    return mapping


def build_id_to_genome_from_project_candidates(project: dict[str, Any]) -> dict[str, str]:
    candidates_cfg = (project.get("candidate_sequences") or {}).get("candidates") or {}
    return {
        str(candidate_id): str(meta.get("source_genome", ""))
        for candidate_id, meta in candidates_cfg.items()
        if meta.get("source_genome")
    }


def write_deer_trigger_summary(
    outdir: Path,
    trigger_rows: list[tuple[str, str, str]],
    detail_lines: list[str],
) -> None:
    """Write a per-genome DEER fallback summary table."""
    outdir.mkdir(parents=True, exist_ok=True)
    lines = [
        "tool                 DEER",
        "role                 structural retrieval fallback after US-align",
        "trigger_rule         run only for source genomes with zero US-align structural candidates",
        "",
        "genome\tstatus\tcommand",
    ]
    lines.extend(f"{genome}\t{status}\t{command}" for genome, status, command in trigger_rows)
    lines.extend(["", "detail"] + detail_lines)
    (outdir / "deer_trigger_summary.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def resolve(path: Path | str | None, root: Path) -> Path:
    if path is None or (isinstance(path, str) and not path.strip()):
        return Path()
    p = Path(path)
    if not p.parts:
        return Path()
    return p if p.is_absolute() else (root / p)


def executable_path(value: str, root: Path) -> str:
    if "/" in value or "\\" in value:
        path = resolve(Path(value), root)
        return str(path) if Path(path).is_file() else value
    return value


def is_executable(value: str, root: Path) -> bool:
    if "/" in value or "\\" in value:
        path = resolve(Path(value), root)
        return path.is_file() and os.access(path, os.X_OK)
    return shutil.which(value) is not None


def collection_cmd(cmd: list[str]) -> str:
    return " ".join(str(part) for part in cmd)


def write_checkpoint(
    path: Path,
    status: str,
    command: list[str],
    outputs: list[str],
    error: str = "",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "step": "deer_fallback",
        "status": status,
        "command": collection_cmd(command),
        "outputs": [str(item) for item in outputs],
        "error": error,
        "next": "run the command above on compute with DEER installed, then inspect raw DEER output files",
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def usalign_evidence(path: Path) -> bool:
    if not path.is_dir():
        return False
    return any(
        (path / filename).is_file() and (path / filename).stat().st_size > 0
        for filename in (
            "structural_hits.tsv",
            "structural_candidates.tsv",
            "usalign_stdout.txt",
        )
    )


def write_summary(
    outdir: Path,
    template_dir: Path,
    candidate_dir: Path,
    usalign_dir: Path,
    tool_version: str,
) -> None:
    lines = [
        "tool                 DEER",
        "role                 structural retrieval fallback after US-align",
        "template_dir         " + str(template_dir),
        "candidate_dir        " + str(candidate_dir),
        "usalign_dir          " + str(usalign_dir),
        "outdir               " + str(outdir),
        "tool_version         " + (tool_version or "unknown"),
        "output_interpretation raw DEER output; map to structural schema only after inspecting columns",
    ]
    (outdir / "deer_run_summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_deer_runtime_compat(outdir: Path) -> Path:
    """Write a small sitecustomize shim so pickled DEER checkpoints can import pathlib._local.PosixPath.

    This is needed for DEER checkpoints saved with an older omegaconf/pathlib
    layout. The shim is only applied to the DEER subprocess through PYTHONPATH.
    """
    site_dir = outdir / "_runtime"
    site_dir.mkdir(parents=True, exist_ok=True)
    shim = site_dir / "sitecustomize.py"
    shim.write_text(
        "import pathlib, sys, types\n"
        "if 'pathlib._local' not in sys.modules:\n"
        "    _local = types.ModuleType('pathlib._local')\n"
        "    _local.PosixPath = pathlib.PosixPath\n"
        "    sys.modules['pathlib._local'] = _local\n",
        encoding="utf-8",
    )
    return site_dir


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project, root = load_project(args)
    deer_cfg = (project.get("tools") or {}).get("deer") or {}
    usalign_cfg = (project.get("tools") or {}).get("usalign") or {}
    out_cfg = project.get("output") or {}

    template_dir = args.template_dir or Path(
        deer_cfg.get("template_pdb_dir") or "inputs/target_structures"
    )
    candidate_dir = args.candidate_dir or Path(
        deer_cfg.get("database_pdb_dir") or usalign_cfg.get("candidate_dir", "outputs/predictions/esmfold")
    )
    outdir = args.outdir or Path(deer_cfg.get("output_dir", "outputs/alignments/deer"))
    usalign_dir = args.usalign_dir or Path(usalign_cfg.get("output_dir", "outputs/alignments/usalign"))
    executable = args.executable or str(deer_cfg.get("executable", "python"))
    script_path = args.script_path or Path(
        deer_cfg.get("script_path") or "/path/to/deer/do_retrieval.py"
    )
    tool_version = args.tool_version or str(deer_cfg.get("tool_version", "DEER GitHub main"))
    device = args.device or str(deer_cfg.get("device", "cpu"))
    allow_without_usalign = (
        args.allow_without_usalign
        if args.allow_without_usalign is not None
        else not bool(deer_cfg.get("require_usalign_evidence", True))
    )
    auto_run = args.auto_run if args.auto_run is not None else bool(deer_cfg.get("auto_run_local", True))
    skip_hf_checkpoint = args.skip_hf_checkpoint or bool(deer_cfg.get("skip_hf_checkpoint", False))
    top_k = args.top_k or int(deer_cfg.get("top_k", 20))
    tmp_dir = args.tmp_dir or Path(str(deer_cfg.get("tmp_dir") or "outputs/alignments/deer/tmp"))
    distance_cutoff = args.distance_cutoff if args.distance_cutoff is not None else float(
        deer_cfg.get("distance_cutoff", 12.0)
    )
    checkpoint = args.checkpoint or Path(out_cfg.get("task_output_dir", "outputs/task")) / "state" / "checkpoint.json"
    ckpt_dir = args.ckpt_dir or Path(
        deer_cfg.get("ckpt_dir") or "/path/to/deer/ckpt"
    )
    deer_model_path = args.deer_model_path or Path(
        deer_cfg.get("deer_model_path") or "/path/to/deer/ckpt/deer_checkpoint.ckpt"
    )

    # CLI args are typed relative to the user's working directory (usually the
    # project directory that contains inputs/ and outputs/). Config defaults
    # stay relative to the discovered project root.
    def cli_or_project(cli_arg: Path | None, configured: Path) -> Path:
        if cli_arg is not None:
            return resolve(cli_arg, Path.cwd())
        return resolve(configured, root)

    template_dir = cli_or_project(args.template_dir, template_dir)
    candidate_dir = cli_or_project(args.candidate_dir, candidate_dir)
    outdir = cli_or_project(args.outdir, outdir)
    usalign_dir = cli_or_project(args.usalign_dir, usalign_dir)
    script_path = cli_or_project(args.script_path, script_path)
    checkpoint = resolve(checkpoint, root)
    ckpt_dir = cli_or_project(args.ckpt_dir, ckpt_dir)
    deer_model_path = cli_or_project(args.deer_model_path, deer_model_path)
    tmp_dir = cli_or_project(args.tmp_dir, tmp_dir)

    if not template_dir.is_dir():
        print(f"template structure directory missing: {template_dir}", file=sys.stderr)
        return 1
    if not candidate_dir.is_dir():
        print(f"candidate structure directory missing: {candidate_dir}", file=sys.stderr)
        return 793
    if not allow_without_usalign and not usalign_evidence(usalign_dir):
        error = (
            "US-align output not found; DEER is a fallback only. Ask the user to run US-align "
            "first or explicitly pass --allow-without-usalign after the user agrees."
        )
        print(error, file=sys.stderr)
        return 2

    missing_genomes, never_seen_genomes = identify_genomes_without_candidates(
        project, usalign_dir, candidate_dir
    )
    if not missing_genomes:
        detail_lines = [
            "All configured source genomes have at least one US-align structural candidate.",
            "DEER fallback not triggered.",
        ]
        write_deer_trigger_summary(outdir, [], detail_lines)
        print("No DEER fallback needed: every configured source genome has a US-align candidate.")
        return 0

    resolved_script = resolve(script_path, root)
    runtime_compat_dir = None
    if not str(deer_model_path).startswith("/path/to/") and deer_model_path.is_file():
        runtime_compat_dir = ensure_deer_runtime_compat(outdir)
    status = "pending" if (not auto_run or not is_executable(executable, root) or not resolved_script.is_file()) else "run"
    trigger_rows: list[tuple[str, str, str]] = []
    detail_lines = [
        "Missing candidate genomes: " + (", ".join(missing_genomes) or "none"),
        "Never seen in US-align output: " + (", ".join(never_seen_genomes) or "none"),
        "DEER is only additional structural evidence; US-align remains primary.",
    ]
    for genome in missing_genomes:
        cmd = [
            executable_path(executable, root),
            str(resolved_script),
            "--template_pdb_dir",
            str(template_dir),
            "--database_pdb_dir",
            str(candidate_dir),
            "--output_dir",
            str(outdir / genome.replace(" ", "_")),
        ]
        if not str(deer_model_path).startswith("/path/to/"):
            cmd += ["--deer_model_path", str(deer_model_path)]
        if not str(ckpt_dir).startswith("/path/to/"):
            cmd += ["--ckpt_dir", str(ckpt_dir)]
        cmd += [
            "--top_k",
            str(top_k),
            "--tmp_dir",
            str(tmp_dir),
        ]
        command_text = collection_cmd(cmd)
        if skip_hf_checkpoint:
            command_text = "HF_HUB_OFFLINE=1 " + command_text
        if runtime_compat_dir is not None:
            command_text = f"PYTHONPATH={runtime_compat_dir}:$PYTHONPATH " + command_text
        trigger_rows.append((genome, status, command_text))
        detail_lines.append(f"DEER candidate for {genome}: {command_text}")

        if status == "run":
            outdir_genome = outdir / genome.replace(" ", "_")
            outdir_genome.mkdir(parents=True, exist_ok=True)
            tmp_dir.mkdir(parents=True, exist_ok=True)
            stdout_file = outdir_genome / "deer_stdout.txt"
            env = os.environ.copy()
            if device == "cpu":
                env["CUDA_VISIBLE_DEVICES"] = ""
            if skip_hf_checkpoint and deer_model_path.is_file():
                env["HF_HUB_OFFLINE"] = "1"
                if skip_hf_checkpoint and ckpt_dir.is_dir():
                    env["HF_DATASETS_CACHE"] = str(ckpt_dir)
            if runtime_compat_dir is not None:
                existing_pythonpath = env.get("PYTHONPATH")
                env["PYTHONPATH"] = (
                    str(runtime_compat_dir) + os.pathsep + existing_pythonpath
                    if existing_pythonpath else str(runtime_compat_dir)
                )
            print(command_text)
            with stdout_file.open("w", encoding="utf-8") as stdout_handle:
                result = subprocess.run(cmd, stdout=stdout_handle, stderr=subprocess.PIPE, text=True, cwd=str(root), env=env)
            if result.returncode != 0:
                write_checkpoint(checkpoint, "failed", cmd, [stdout_file], result.stderr[-2000:])
                write_deer_trigger_summary(outdir, trigger_rows, detail_lines)
                return result.returncode

            similarity_csv = outdir_genome / "similarity.csv"
            if similarity_csv.is_file():
                parsed_candidates = outdir_genome / "structural_candidates.tsv"
                all_source_genomes = configured_source_genomes(project)
                parse_cmd = [
                    sys.executable,
                    str(Path(__file__).parent / "parse_deer.py"),
                    "--input",
                    str(similarity_csv),
                    "--output",
                    str(parsed_candidates),
                    "--distance-cutoff",
                    str(distance_cutoff),
                    "--organism",
                    genome,
                    "--candidate-dir",
                    str(candidate_dir),
                    "--source-genomes",
                    ",".join(all_source_genomes),
                ]
                print("PARSING_DEER_RESULTS")
                subprocess.run(parse_cmd, check=False, cwd=str(root))

            output_files = sorted(path for path in outdir_genome.iterdir() if path.is_file())
            write_summary(outdir_genome, template_dir, candidate_dir, usalign_dir, tool_version)
            write_checkpoint(checkpoint, "completed", cmd, output_files + [outdir_genome / "deer_run_summary.txt"])
            print(f"DEER retrieval for {genome} completed.")
        else:
            write_checkpoint(
                checkpoint,
                "pending",
                cmd,
                [],
                f"DEER fallback triggered for {genome}; tool/data not accessible or auto_run disabled",
            )

    write_deer_trigger_summary(outdir, trigger_rows, detail_lines)
    if status == "pending":
        print("DEER not run locally. Returned commands are per missing candidate genome.")
        for _, _, command_text in trigger_rows:
            print("REQUIRED_COMMAND")
            print(command_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
