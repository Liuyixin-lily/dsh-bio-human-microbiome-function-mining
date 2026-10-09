#!/usr/bin/env python3
"""Prepare parallel US-align execution files inside an isolated acceptance dir."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    root = Path(argv[0] if argv else ".").resolve()
    proj = json.loads((root / "human_microbiome_function_mining/projects/nsmase2_hsmd3_demo.project.json").read_text(encoding="utf-8"))
    ua_cfg = (proj.get("tools") or {}).get("usalign") or {}
    target = (root / "inputs/SMPD3_HUMAN_5UVG.pdb").resolve()
    cand_dir = (root / "inputs/candidate_structures").resolve()
    exe = ua_cfg.get("executable", "USalign")
    parts_dir = (root / "outputs/alignments/run_full_accept/.parts").resolve()
    parts_dir.mkdir(parents=True, exist_ok=True)
    done = {p.stem for p in parts_dir.glob("*.txt") if p.is_file()}
    files = sorted(
        p
        for p in cand_dir.iterdir()
        if p.is_file() and p.suffix.lower() in (".pdb", ".cif")
    )
    remaining = [p for p in files if p.stem not in done]
    print("total", len(files), "done", len(done), "remaining", len(remaining))
    out = root / "logs" / "03_usalign_remaining.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for p in remaining:
            fh.write(f"{p}\n")
    script = root / "logs" / "03_usalign_one.sh"
    lines = [
        "#!/bin/bash",
        "set -euo pipefail",
        f'cd "{root}"',
        f'EXE="{exe}"',
        f'TARGET="{target}"',
        f'PARTS="{parts_dir}"',
        f'LOG="logs/03_usalign_parallel.log"',
        'chunk="$1"',
        'while IFS= read -r pdb || [ -n "$pdb" ]; do',
        '  name=$(basename "$pdb" .pdb)',
        '  name=${name%.cif}',
        '  out="$PARTS/$name.txt"',
        '  if [ -s "$out" ]; then continue; fi',
        '  echo "$(date +%H:%M:%S) $name" >> "$LOG"',
        '  "$EXE" "$TARGET" "$pdb" -outfmt 2 > "$out" 2>>"$LOG" || echo "FAIL:$name" >> "$LOG"',
        'done < "$chunk"',
    ]
    script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    script.chmod(0o755)
    launcher = root / "logs" / "03_usalign_parallel_launch.sh"
    lines2 = [
        "#!/bin/bash",
        "set -euo pipefail",
        f'cd "{root}"',
        "SPLIT=logs/03_usalign_chunks",
        "rm -rf \"$SPLIT\"",
        "mkdir -p \"$SPLIT\"",
        "split -n l/32 -d logs/03_usalign_remaining.txt \"$SPLIT/chunk_\"",
        "rm -f logs/03_usalign_parallel.pids",
        "for c in \"$SPLIT\"/chunk_*; do",
        '  [ -s "$c" ] && nohup logs/03_usalign_one.sh "$c" >> logs/03_usalign_runner.log 2>&1 &',
        '  echo $! >> logs/03_usalign_parallel.pids',
        "done",
        "echo started $(wc -l logs/03_usalign_runner.log) runner_log",
    ]
    launcher.write_text("\n".join(lines2) + "\n", encoding="utf-8")
    launcher.chmod(0o755)
    print("wrote", out)
    print("wrote", script)
    print("wrote", launcher)
    print("root", root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
