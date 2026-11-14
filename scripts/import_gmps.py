#!/usr/bin/env python3
"""Bring GMPS (Human Gut Microbial Protein Structure database) data into the pipeline.

What GMPS is (verified from its Dryad record, doi:10.5061/dryad.gtht76hx2, and the
Cell Host & Microbe paper): ~2.7 million AlphaFold2-predicted protein structures from
968 human gut bacterial genomes plus 1,255 phage/prophage genomes, packaged per species
and shipped together with protein sequences and functional annotation from DRAM v1.3,
microbeannotator v2.0.5 and eggnog-mapper v2.1.9. Structures were produced with
AlphaFold2 / MODELLER 9.8 and searched with US-align.

That makes GMPS a **candidate pool and structural search engine for the gut**, not a
target library. This script therefore integrates it as an input source:

1. `--species-map` — from `bacteria_N.tar.gz_Species.txt`, tell the user which tarball
   part(s) contain the taxa they care about, so they do not blind-download ~130 GB.
2. `--hits` — adapt an exported GMPS structural-search result into
   `structural_candidates.tsv`.
3. `--annotation` — adapt an extracted `bacteria_final_annotation` table into
   `source_feature_annotations.tsv`, which is the existing annotation evidence layer.

Honesty rules, because a dataset this size invites over-reading:

- **Nothing is guessed.** Column meaning must be given with `--map`, or inferred only
  from a fixed alias list; an unmapped required field is a hard error, and `--dry-run`
  prints the mapping for confirmation before anything is written.
- **No fabricated metrics.** If the export has no TM/RMSD columns, they stay empty; the
  script never converts an arbitrary "score" into a TM-score unless the user maps it
  explicitly, and even then it records that as a user-declared mapping.
- **Provenance is mandatory.** Every output carries a sidecar JSON with the source file,
  its sha256, the row count, the mapping used, and the GMPS version the user declared.
- **GMPS structures are predictions**, and a structural hit is not a function. The
  adapters never set a functional verdict.

Usage:

    python3 scripts/import_gmps.py --species-map bacteria_N.tar.gz_Species.txt \\
        --taxa "Akkermansia muciniphila,Faecalibacterium prausnitzii"

    python3 scripts/import_gmps.py --hits gmps_search_export.tsv \\
        --map "query=template_id,gene=protein_accession,species=organism_or_strain,tm1=tm_score_1" \\
        --tool-version "GMPS_v1 (2026-11 export)" --dry-run \\
        --output outputs/task/structural_candidates.gmps.tsv

    python3 scripts/import_gmps.py --annotation bacteria_final_annotation.tsv \\
        --map "protein=protein_accession,product=product,ec=ec_number" \\
        --source-file bacteria_final_annotation.tsv \\
        --output outputs/task/source_feature_annotations.gmps.tsv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

STRUCTURAL_FIELDS = [
    "candidate_id",
    "representative_id",
    "assembly_accession",
    "protein_accession",
    "organism_or_strain",
    "annotation",
    "template_id",
    "tm_score_1",
    "tm_score_2",
    "tm_score_mean",
    "rmsd",
    "aligned_length",
    "sequence_identity",
    "plddt_mean",
    "tool",
    "tool_version",
    "structural_score",
    "prediction_pdb",
    "catalytic_residue_hits",
    "pocket_similarity",
    "notes",
    "structure_support",
]

ANNOTATION_FIELDS = [
    "candidate_id",
    "protein_accession",
    "source_file",
    "feature_type",
    "product",
    "protein_name",
    "gene",
    "locus_tag",
    "ec_number",
    "pfam",
    "interpro",
    "tigrfam",
    "cazy",
    "kegg_orthology",
    "cog",
    "go_terms",
    "description",
    "annotation_source",
    "notes",
]

# Accepted aliases for the structural-search export. Deliberately conservative: only
# names that cannot plausibly mean something else.
STRUCTURAL_ALIASES: dict[str, list[str]] = {
    "template_id": ["template", "template_id", "template_pdb"],
    "protein_accession": ["protein_accession", "accession", "protein_id", "uniprot"],
    "organism_or_strain": ["organism", "species", "organism_or_strain", "strain", "taxon"],
    "tm_score_1": ["tm1", "tm_score_1", "tm_score1", "tm-score-1"],
    "tm_score_2": ["tm2", "tm_score_2", "tm_score2", "tm-score-2"],
    "tm_score_mean": ["tm_score_mean", "tm_mean", "tm"],
    "rmsd": ["rmsd", "RMSD"],
    "aligned_length": ["aligned_length", "aln_len", "length_aligned", "n_aligned"],
    "sequence_identity": ["seq_id", "identity", "sequence_identity", "pident"],
    "plddt_mean": ["plddt", "plddt_mean", "mean_plddt"],
    "prediction_pdb": ["pdb", "structure", "structure_file", "pdb_file", "model"],
}

ANNOTATION_ALIASES: dict[str, list[str]] = {
    "protein_accession": ["protein_accession", "protein", "accession", "protein_id", "gene_id"],
    "product": ["product", "product_name"],
    "protein_name": ["protein_name", "name"],
    "gene": ["gene", "gene_symbol"],
    "locus_tag": ["locus_tag", "locus", "locus_id"],
    "ec_number": ["ec", "ec_number", "EC"],
    "pfam": ["pfam", "pfam_id"],
    "interpro": ["interpro", "interpro_id"],
    "tigrfam": ["tigrfam", "tigrfam_id"],
    "cazy": ["cazy", "cazy_id"],
    "kegg_orthology": ["kegg", "ko", "kegg_orthology"],
    "cog": ["cog", "cog_id"],
    "go_terms": ["go", "go_terms", "go_id"],
    "description": ["description", "desc", "annotation"],
}

TM_THRESHOLD = 0.5


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sniff_delimiter(path: Path) -> str:
    sample = path.read_text(encoding="utf-8", errors="replace")[:8192]
    for delimiter in ("\t", ",", ";"):
        if sample.count(delimiter) >= max(1, sample.count("\n")):
            return delimiter
    return "\t"


def read_table(path: Path) -> tuple[list[str], list[dict[str, str]], str]:
    delimiter = sniff_delimiter(path)
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        rows = list(reader)
        return list(reader.fieldnames or []), rows, delimiter


def parse_map(pairs: list[str] | None) -> dict[str, str]:
    """--map entries are `source_column=target_field`."""
    mapping: dict[str, str] = {}
    for item in pairs or []:
        # accept both repeated flags and one comma-separated flag:
        #   --map a=b --map c=d      or      --map "a=b,c=d"
        for pair in item.split(","):
            pair = pair.strip()
            if not pair:
                continue
            if "=" not in pair:
                raise SystemExit(f"error: --map entry must be source=target, got {pair!r}")
            source, target = pair.split("=", 1)
            mapping[source.strip()] = target.strip()
    return mapping


def resolve_mapping(
    headers: list[str],
    explicit: dict[str, str],
    aliases: dict[str, list[str]],
    required: tuple[str, ...],
    warnings: list[str],
) -> dict[str, str]:
    """Build target_field -> source_column. Explicit wins; aliases only fill gaps."""
    lowered = {header.strip().lower(): header for header in headers}
    resolved: dict[str, str] = {}
    for source, target in explicit.items():
        if source not in headers and source.strip().lower() not in lowered:
            raise SystemExit(
                f"error: --map names a column that is not in the file: {source!r}; "
                f"available columns: {', '.join(headers)}"
            )
        column = source if source in headers else lowered[source.strip().lower()]
        resolved[target] = column
    for target, names in aliases.items():
        if target in resolved:
            continue
        for name in names:
            if name.lower() in lowered:
                resolved[target] = lowered[name.lower()]
                break
    for target in required:
        if target not in resolved:
            raise SystemExit(
                f"error: cannot determine the source column for required field {target!r}. "
                "Give it explicitly, e.g. --map \"<column>={target}\". Available columns: "
                + ", ".join(headers)
            )
    if explicit:
        warnings.append("用户用 --map 显式声明了列映射；未声明的列不会被推断覆盖")
    consumed = set(resolved.values())
    unused = [header for header in headers if header not in consumed]
    if unused:
        warnings.append(
            "以下列没有被导入（需要保留就显式 --map）：" + ", ".join(unused)
        )
    return resolved


def get(row: dict[str, str], mapping: dict[str, str], target: str) -> str:
    column = mapping.get(target)
    if not column:
        return ""
    return (row.get(column) or "").strip()


def as_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def structural_rows(
    rows: list[dict[str, str]],
    mapping: dict[str, str],
    tool_version: str,
    warnings: list[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    declared_tm = "tm_score_mean" in mapping
    if declared_tm and "tm_score_1" not in mapping and "tm_score_2" not in mapping:
        warnings.append(
            "只提供了 tm_score_mean：无法按双向阈值判定结构支持，structure_support 一律留空"
        )
    for index, row in enumerate(rows, 1):
        tm1 = as_float(get(row, mapping, "tm_score_1"))
        tm2 = as_float(get(row, mapping, "tm_score_2"))
        tm_mean = as_float(get(row, mapping, "tm_score_mean"))
        if tm_mean is None and tm1 is not None and tm2 is not None:
            tm_mean = (tm1 + tm2) / 2
        support = ""
        if tm1 is not None and tm2 is not None:
            support = "1" if (tm1 >= TM_THRESHOLD and tm2 >= TM_THRESHOLD) else "0"
        accession = get(row, mapping, "protein_accession")
        out.append(
            {
                "candidate_id": accession or f"gmps_row{index}",
                "representative_id": accession,
                "assembly_accession": "",
                "protein_accession": accession,
                "organism_or_strain": get(row, mapping, "organism_or_strain"),
                "annotation": get(row, mapping, "annotation"),
                "template_id": get(row, mapping, "template_id") or "user_submitted_template",
                "tm_score_1": "" if tm1 is None else f"{tm1:.4f}",
                "tm_score_2": "" if tm2 is None else f"{tm2:.4f}",
                "tm_score_mean": "" if tm_mean is None else f"{tm_mean:.4f}",
                "rmsd": get(row, mapping, "rmsd"),
                "aligned_length": get(row, mapping, "aligned_length"),
                "sequence_identity": get(row, mapping, "sequence_identity"),
                "plddt_mean": get(row, mapping, "plddt_mean"),
                "tool": "GMPS",
                "tool_version": tool_version,
                "structural_score": "" if tm_mean is None else f"{tm_mean:.4f}",
                "prediction_pdb": get(row, mapping, "prediction_pdb"),
                "catalytic_residue_hits": "",
                "pocket_similarity": "",
                "notes": "imported from GMPS structural search; GMPS models are AlphaFold2 predictions",
                "structure_support": support,
            }
        )
    out.sort(key=lambda r: (-(float(r["tm_score_mean"]) if r["tm_score_mean"] else -1.0), r["candidate_id"]))
    return out


def annotation_rows(
    rows: list[dict[str, str]],
    mapping: dict[str, str],
    source_file: str,
    annotation_source: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        accession = get(row, mapping, "protein_accession")
        if not accession:
            continue
        out.append(
            {
                "candidate_id": accession,
                "protein_accession": accession,
                "source_file": source_file,
                "feature_type": "fasta_header" if source_file.endswith((".faa", ".fasta")) else "cds",
                "product": get(row, mapping, "product"),
                "protein_name": get(row, mapping, "protein_name"),
                "gene": get(row, mapping, "gene"),
                "locus_tag": get(row, mapping, "locus_tag"),
                "ec_number": get(row, mapping, "ec_number"),
                "pfam": get(row, mapping, "pfam"),
                "interpro": get(row, mapping, "interpro"),
                "tigrfam": get(row, mapping, "tigrfam"),
                "cazy": get(row, mapping, "cazy"),
                "kegg_orthology": get(row, mapping, "kegg_orthology"),
                "cog": get(row, mapping, "cog"),
                "go_terms": get(row, mapping, "go_terms"),
                "description": get(row, mapping, "description"),
                "annotation_source": annotation_source,
                "notes": "imported from GMPS; annotation text passed through unchanged",
            }
        )
    return out


def matches_target(
    row: dict[str, str],
    mapping: dict[str, str],
    target_ec: str | None,
    target_names: list[str],
) -> tuple[bool, str]:
    """Coarse annotation screen. Returns (keep, reason).

    This only filters on fields the user mapped; it never infers a function from a
    partial match beyond the match itself.
    """
    if target_ec:
        ec = get(row, mapping, "ec_number")
        wanted = target_ec.strip()
        if not ec:
            return False, ""
        if wanted.endswith("."):
            if ec.startswith(wanted) or ec.startswith(wanted.rstrip(".")):
                return True, f"EC {ec} matches prefix {wanted}"
            return False, ""
        if ec == wanted:
            return True, f"EC {ec} exact"
        # allow family-level match such as 3.1.4.- against 3.1.4.12
        parts_wanted = wanted.split(".")
        parts_ec = ec.split(".")
        if len(parts_wanted) == len(parts_ec) and all(
            w == "-" or w == e for w, e in zip(parts_wanted, parts_ec)
        ):
            return True, f"EC {ec} matches family {wanted}"
        return False, ""
    if target_names:
        haystack = " ".join(
            get(row, mapping, field)
            for field in ("product", "protein_name", "description", "gene")
        ).lower()
        for name in target_names:
            if name and name.lower() in haystack:
                return True, f"名称命中 {name!r}"
        return False, ""
    return True, ""


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_provenance(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# species map
# ---------------------------------------------------------------------------


def parse_species_map(path: Path) -> dict[str, list[str]]:
    """`bacteria_N.tar.gz_Species.txt` maps each tarball part to the species it holds."""
    parts: dict[str, list[str]] = {}
    current: str | None = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.lower().endswith((".tar.gz", ".tgz", ".zip")) or "bacteria_" in line.lower():
            current = line
            parts.setdefault(current, [])
        elif current is not None:
            parts[current].append(line)
    return parts


def select_parts(parts: dict[str, list[str]], wanted: list[str]) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for taxon in wanted:
        needle = taxon.strip().lower()
        if not needle:
            continue
        for part, species in parts.items():
            for name in species:
                if needle in name.lower() or name.lower() in needle:
                    hits.setdefault(part, [])
                    if taxon.strip() not in hits[part]:
                        hits[part].append(taxon.strip())
                    break
    return hits


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import GMPS (gut microbial protein structure database) data into the plugin's tables.",
    )
    parser.add_argument("--species-map", type=Path, default=None,
                        help="bacteria_N.tar.gz_Species.txt from the GMPS archive.")
    parser.add_argument("--taxa", default=None,
                        help="Comma-separated taxa to locate inside the species map.")
    parser.add_argument("--hits", type=Path, default=None,
                        help="Exported GMPS structural-search result table.")
    parser.add_argument("--annotation", type=Path, default=None,
                        help="Extracted GMPS annotation table (e.g. bacteria_final_annotation).")
    parser.add_argument("--map", dest="mapping", action="append", default=None,
                        help="source_column=target_field, repeatable.")
    parser.add_argument("--tool-version", default="GMPS_v1 (version not stated by user)",
                        help="Recorded as tool_version in the structural table.")
    parser.add_argument("--annotation-source", default="GMPS",
                        help="Recorded as annotation_source (e.g. DRAM, microbeannotator, eggnog).")
    parser.add_argument("--source-file", default=None,
                        help="Original file path recorded in source_feature_annotations.")
    parser.add_argument("--output", type=Path, default=None, help="Output TSV.")
    parser.add_argument("--provenance", type=Path, default=None, help="Provenance JSON sidecar.")
    parser.add_argument("--target-ec", default=None,
                        help="With --annotation: keep only rows whose mapped EC matches this (prefix match, e.g. 3.1.4.12 or 3.1.4.).")
    parser.add_argument("--target-name", default=None,
                        help="With --annotation: comma-separated names/products/substrings to keep.")
    parser.add_argument("--dry-run", action="store_true", help="Print the resolved mapping and row counts; write nothing.")
    parser.add_argument(
        "--inspect",
        type=Path,
        default=None,
        metavar="FILE",
        help="Show delimiter, columns, row count and the mapping the alias tables would suggest. Writes nothing.",
    )
    return parser.parse_args(argv)


def inspect_table(path: Path) -> int:
    """Show what the file looks like and what the alias tables can infer.

    This is the step to run first, because GMPS's export columns are not documented:
    see the real headers, then decide the mapping explicitly.
    """
    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2
    headers, rows, delimiter = read_table(path)
    print(f"file       : {path}")
    print(f"delimiter  : {delimiter!r}")
    print(f"rows       : {len(rows)}")
    print(f"columns    : {len(headers)}")
    print()
    print("列名字:")
    for index, header in enumerate(headers, 1):
        print(f"  {index:2}. {header}")
    print()
    for label, aliases in (("结构命中表", STRUCTURAL_ALIASES), ("注释表", ANNOTATION_ALIASES)):
        lowered = {header.strip().lower(): header for header in headers}
        inferred = {}
        for target, names in aliases.items():
            for name in names:
                if name.lower() in lowered:
                    inferred[target] = lowered[name.lower()]
                    break
        if not inferred:
            continue
        print(f"{label}：按别名表可推断的映射（仍需你确认）")
        for target, column in sorted(inferred.items()):
            print(f"  {column!r} -> {target}")
        unmapped = [h for h in headers if h not in set(inferred.values())]
        if unmapped:
            print(f"  未映射: {', '.join(unmapped)}")
        print()
    print(
        "下一步：用 --map 显式声明列含义后 --dry-run；未确认的列不会被导入。"
        "歧义名（如 query / target）不会自动映射，需要你自己指定。"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    warnings: list[str] = []

    if args.inspect is not None:
        return inspect_table(args.inspect)

    if args.species_map is not None:
        if not args.species_map.is_file():
            print(f"error: species map not found: {args.species_map}", file=sys.stderr)
            return 2
        parts = parse_species_map(args.species_map)
        if not parts:
            print("error: no tarball parts recognised in the species map", file=sys.stderr)
            return 2
        wanted = [t for t in (args.taxa or "").split(",") if t.strip()]
        if not wanted:
            print(f"识别到 {len(parts)} 个分卷：")
            for part, species in sorted(parts.items()):
                print(f"  {part}: {len(species)} 个物种")
            print("\n用 --taxa \"Genus species,...\" 查某个物种在哪个分卷里。")
            return 0
        hits = select_parts(parts, wanted)
        missing = [t for t in wanted if not any(t in v for v in hits.values())]
        print("需要下载的分卷：")
        if hits:
            for part, matched in sorted(hits.items()):
                print(f"  {part}  ← {', '.join(matched)}")
        else:
            print("  （没有任何分卷匹配）")
        print(f"\n完整数据约 130 GB（压缩）/ 1.3 TB（解压），只取需要的分卷；"
              "注释表 bacteria_final_annotation.zip 只有 250 MB，通常先拉它。")
        if missing:
            print(f"\n未匹配到的物种（名字可能不同）：{', '.join(missing)}", file=sys.stderr)
        return 0

    if args.hits is None and args.annotation is None:
        print(
            "error: nothing to import. Use --species-map, --hits or --annotation.",
            file=sys.stderr,
        )
        return 2

    explicit = parse_map(args.mapping)

    if args.hits is not None:
        if not args.hits.is_file():
            print(f"error: hits file not found: {args.hits}", file=sys.stderr)
            return 2
        headers, rows, delimiter = read_table(args.hits)
        mapping = resolve_mapping(
            headers, explicit, STRUCTURAL_ALIASES,
            required=("protein_accession",), warnings=warnings,
        )
        if not any(k in mapping for k in ("tm_score_1", "tm_score_2", "tm_score_mean")):
            print(
                "error: 这个导出里找不到任何相似度指标（TM-score）。"
                "没有相似度就无法排序，也不会替你编一个；请用 --map 指定哪一列是 TM。",
                file=sys.stderr,
            )
            return 2
        if "template_id" not in mapping:
            warnings.append(
                "导出里没有 template 列：模板记作 user-submitted template，"
                "结构命中与哪个模板比对需在报告里写清"
            )
        structural = structural_rows(rows, mapping, args.tool_version, warnings)
        supported = sum(1 for r in structural if r["structure_support"] == "1")
        print(f"结构命中表：{len(structural)} 行（分隔符 {delimiter!r}），双向 TM ≥ {TM_THRESHOLD} 的有 {supported} 行")
        print("列映射：")
        for target, column in sorted(mapping.items()):
            print(f"  {column!r} -> {target}")
        if args.dry_run:
            for warning in warnings:
                print(f"  warn: {warning}")
            print("--dry-run：未写入文件。确认映射后用去掉 --dry-run 重跑。")
            return 0
        if args.output is None:
            print("error: --hits needs --output", file=sys.stderr)
            return 2
        write_tsv(args.output, structural, STRUCTURAL_FIELDS)
        print(f"wrote {args.output}")
        provenance_path = args.provenance or args.output.with_suffix(".provenance.json")
        write_provenance(provenance_path, {
            "source": "GMPS",
            "source_file": str(args.hits),
            "source_sha256": sha256_of(args.hits),
            "rows_in": len(rows),
            "rows_out": len(structural),
            "column_mapping": mapping,
            "tool_version": args.tool_version,
            "tm_threshold": TM_THRESHOLD,
            "dry_run": False,
            "notes": [
                "GMPS structures are AlphaFold2 predictions, not experimental structures.",
                "A structural hit is not a functional assignment.",
                "structure_support follows the plugin's bidirectional TM policy.",
            ],
            "warnings": warnings,
        })
        print(f"wrote {provenance_path}")
        for warning in warnings:
            print(f"  warn: {warning}", file=sys.stderr)

    if args.annotation is not None:
        if not args.annotation.is_file():
            print(f"error: annotation file not found: {args.annotation}", file=sys.stderr)
            return 2
        headers, rows, delimiter = read_table(args.annotation)
        mapping = resolve_mapping(
            headers, explicit, ANNOTATION_ALIASES,
            required=("protein_accession",), warnings=warnings,
        )
        source_file = args.source_file or str(args.annotation)
        target_names = [n for n in (args.target_name or "").split(",") if n.strip()]
        screening = bool(args.target_ec or target_names)
        reasons: list[str] = []
        if screening:
            kept_rows = []
            for row in rows:
                keep, reason = matches_target(row, mapping, args.target_ec, target_names)
                if keep:
                    kept_rows.append(row)
                    reasons.append(reason)
            print(
                f"注释层粗筛：{len(rows)} 行中命中 {len(kept_rows)} 行"
                f"（EC={args.target_ec or '—'}；名称={args.target_name or '—'}）"
            )
            rows = kept_rows
        annotations = annotation_rows(rows, mapping, source_file, args.annotation_source)
        print(f"注释表：{len(annotations)} 行（分隔符 {delimiter!r}）")
        if screening:
            for annotation, reason in zip(annotations, reasons):
                print(f"  {annotation['protein_accession']}  ← {reason}")
        print("列映射：")
        for target, column in sorted(mapping.items()):
            print(f"  {column!r} -> {target}")
        if args.dry_run:
            for warning in warnings:
                print(f"  warn: {warning}")
            print("--dry-run：未写入文件。")
            return 0
        if args.output is None:
            print("error: --annotation needs --output", file=sys.stderr)
            return 2
        write_tsv(args.output, annotations, ANNOTATION_FIELDS)
        print(f"wrote {args.output}")
        provenance_path = args.provenance or args.output.with_suffix(".provenance.json")
        write_provenance(provenance_path, {
            "source": "GMPS",
            "source_file": str(args.annotation),
            "source_sha256": sha256_of(args.annotation),
            "rows_in": len(rows),
            "rows_out": len(annotations),
            "column_mapping": mapping,
            "annotation_source": args.annotation_source,
            "screen": {
                "target_ec": args.target_ec,
                "target_name": args.target_name,
                "rows_kept": len(annotations),
            },
            "notes": [
                "Annotation text is passed through unchanged; nothing is inferred.",
                "GMPS ships DRAM / microbeannotator / eggnog-mapper annotations; record which one this is.",
            ],
            "warnings": warnings,
        })
        print(f"wrote {provenance_path}")
        for warning in warnings:
            print(f"  warn: {warning}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
