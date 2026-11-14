#!/usr/bin/env python3
"""Report divergence between the two copies every bundled skill exists in.

`src/skills.js` loads `skills/<name>.md`, so that flat file is what the agent actually reads. Each
skill also ships `skills/<name>/SKILL.md`, and the two have drifted: the flat copies carry sections
the directory copies lack and vice versa (240 differing lines in structure-prediction alone). Nothing
reported that, so edits to one silently never reach the other.

This script only reports. Merging is a content decision — each drifted pair needs a human to decide
which text wins — so the script exits non-zero and lists the pairs with their line deltas.

    python3 scripts/check_skill_copies.py            # report
    python3 scripts/check_skill_copies.py --json
    python3 scripts/check_skill_copies.py --quiet    # exit code only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"


def pairs() -> list[tuple[str, Path, Path]]:
    found: list[tuple[str, Path, Path]] = []
    for directory in sorted(path for path in SKILLS.iterdir() if path.is_dir()):
        skill_md = directory / "SKILL.md"
        flat = SKILLS / f"{directory.name}.md"
        if flat.is_file():
            found.append((directory.name, skill_md, flat))
    return found


def differing_lines(left: Path, right: Path) -> int:
    if not left.is_file() or not right.is_file():
        return -1
    left_lines = [line.rstrip() for line in left.read_text(encoding="utf-8").splitlines()]
    right_lines = [line.rstrip() for line in right.read_text(encoding="utf-8").splitlines()]
    if left_lines == right_lines:
        return 0
    import difflib

    count = 0
    for line in difflib.unified_diff(left_lines, right_lines, lineterm="", n=0):
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report skill copy divergence.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    results = []
    for name, skill_md, flat in pairs():
        delta = differing_lines(skill_md, flat)
        results.append({
            "skill": name,
            "directory_copy": str(skill_md.relative_to(ROOT)),
            "flat_copy": str(flat.relative_to(ROOT)),
            "differing_lines": delta,
            "loaded_by_runtime": str(flat.relative_to(ROOT)),
        })
    drifted = [row for row in results if row["differing_lines"] != 0]

    if args.json:
        print(json.dumps({"skills": results, "drifted": len(drifted)}, ensure_ascii=False, indent=2))
        return 0 if not drifted else 1
    if args.quiet:
        return 0 if not drifted else 1

    print(f"{len(results)} skill(s) with both copies; runtime loads the flat `<name>.md`.")
    if not drifted:
        print("no divergence.")
        return 0
    print(f"{len(drifted)} drifted:\n")
    for row in sorted(drifted, key=lambda r: -r["differing_lines"]):
        print(f"  {row['skill']:34} {row['differing_lines']:4} differing line(s)")
        print(f"      runtime : {row['flat_copy']}")
        print(f"      unused  : {row['directory_copy']}")
    print(
        "\nEach pair needs a human decision: the two copies contain different guidance, so neither is "
        "a superset. Sync one way only after comparing the sections (the runtime copy is the one that "
        "actually runs)."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
