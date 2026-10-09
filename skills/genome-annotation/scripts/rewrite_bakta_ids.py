#!/usr/bin/env python3
"""Rewrite Bakta internal tags to original sample names in text outputs."""

from __future__ import annotations

import argparse
from pathlib import Path


TEXT_SUFFIXES = {
    ".faa",
    ".ffn",
    ".fna",
    ".gff3",
    ".tsv",
    ".json",
    ".embl",
    ".gbff",
    ".txt",
    ".svg",
}


def rewrite_file(path: Path, tag: str, sample: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False

    updated = text.replace(tag, sample)
    if updated == text:
        return False

    path.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outdir", required=True, type=Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--sample", required=True)
    args = parser.parse_args()

    if not args.outdir.is_dir():
        raise SystemExit(f"Output directory does not exist: {args.outdir}")

    changed = 0
    for path in args.outdir.rglob("*"):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            if rewrite_file(path, args.tag, args.sample):
                changed += 1

    print(f"Rewrote sequence IDs in {changed} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
