#!/usr/bin/env python3
"""Build NCBI download URL lists from GCF/GCA accessions.

Examples:
  python3 build_download_links.py --download-summary bacteria
  python3 build_download_links.py --gcf gcf_list.tsv --assembly-summary assembly_summary.txt --out download_urls.txt
"""

from __future__ import annotations

import argparse
import csv
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


TSV_DIALECT = "excel-tab"
DEFAULT_FILES = [
    "genomic.fna.gz",
    "protein.faa.gz",
    "cds_from_genomic.fna.gz",
    "genomic.gbff.gz",
    "genomic.gff.gz",
]
DEFAULT_SUMMARY_PATHS = {
    "refseq": Path("ncbi_assembly_summary_refseq.txt"),
    "genbank": Path("ncbi_assembly_summary_genbank.txt"),
}


def is_assembly_accession(value: str) -> bool:
    return value.upper().startswith(("GCF", "GCA"))


def accession_source(accession: str) -> str:
    return "refseq" if accession.upper().startswith("GCF") else "genbank"


def read_users(users_path: Path) -> dict[str, dict[str, str]]:
    """Return the GCF/GCA accessions provided by the user."""
    out: dict[str, dict[str, str]] = {}
    suffix = users_path.suffix.lower() if users_path.suffix else ""
    if suffix in (".tsv", ".tab", ".txt"):
        with users_path.open("r", encoding="utf-8", newline="", errors="replace") as handle:
            sample = handle.read(2048)
        if sample.lstrip().startswith("assembly_accession"):
            handle.seek(0)
            rows = list(csv.DictReader(handle, dialect=TSV_DIALECT))
            for row in rows:
                acc = (row.get("assembly_accession") or row.get("accession") or "").strip()
                if is_assembly_accession(acc):
                    out[acc.upper()] = row
            if out:
                return out

    for line in users_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.replace(",", "\t").split("\t")
        for part in parts:
            part = part.strip()
            if is_assembly_accession(part):
                out[part.upper()] = {"assembly_accession": part}
    return out


def build_summary_dict(summary_path: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    with summary_path.open("r", encoding="utf-8", newline="", errors="replace") as handle:
        for raw in handle:
            if raw.startswith("#"):
                continue
            line = raw.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 20:
                continue
            acc = parts[0].strip()
            if is_assembly_accession(acc):
                out[acc] = {"ftp_path": parts[19].strip()}
    return out


def download_summary(url: str, target: Path) -> bool:
    if target.exists() and target.stat().st_size:
        print(f"[summary] exists: {target}")
        return True
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=180) as response:
            tmp = target.with_suffix(".tmp")
            with tmp.open("wb") as output:
                while True:
                    chunk = response.read(1 << 16)
                    if not chunk:
                        break
                    output.write(chunk)
        tmp.replace(target)
        print(f"[summary] downloaded -> {target}")
        return True
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"ERROR: failed to download summary: {exc}", file=sys.stderr)
        return False


def determine_sources(accessions: list[str], requested: str) -> list[str]:
    if requested != "auto":
        mismatches = [acc for acc in accessions if accession_source(acc) != requested]
        if mismatches:
            print(
                f"ERROR: source is {requested}, but these accessions use another source: "
                + ", ".join(mismatches),
                file=sys.stderr,
            )
            return []
        return [requested]
    present = {accession_source(acc) for acc in accessions}
    return [source for source in ("refseq", "genbank") if source in present]


def resolve_summary_paths(explicit: list[Path], sources: list[str]) -> list[Path]:
    if explicit:
        if len(explicit) != len(sources):
            print(
                f"ERROR: {len(sources)} assembly summaries are required for {len(sources)} "
                f"sources, but {len(explicit)} were provided.",
                file=sys.stderr,
            )
            return []
        return explicit
    return [DEFAULT_SUMMARY_PATHS[source] for source in sources]


def url_is_available(url: str) -> bool:
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": "genome-download/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return 200 <= response.status < 400
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 410):
            return False
        raise RuntimeError(f"availability check failed for {url}: {exc}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"availability check failed for {url}: {exc}") from exc


def write_urls(rows: list[str], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for url in rows:
            handle.write(url + "\n")
    print(f"[links] wrote {len(rows)} URLs -> {out}")


def write_skipped(rows: list[str], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(row + "\n")
    print(f"[skipped] wrote {len(rows)} accessions -> {out}")


def parse_file_args(values: list[str]) -> list[str]:
    files: list[str] = []
    for value in values:
        files.extend(part.strip() for part in value.split(",") if part.strip())
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--gcf",
        "--accessions",
        dest="gcf",
        help="GCF/GCA TSV or list from build_gcf_list.py or the user",
    )
    parser.add_argument(
        "--assembly-summary",
        action="append",
        type=Path,
        help="assembly_summary.txt path; provide one per source for mixed GCF/GCA input",
    )
    parser.add_argument("--out", help="output URL list")
    parser.add_argument(
        "--files",
        nargs="+",
        default=DEFAULT_FILES,
        help="NCBI file suffixes to include (comma or space separated)",
    )
    parser.add_argument(
        "--download-summary",
        nargs="?",
        const="bacteria",
        help="RefSeq or GenBank group to download summaries for (default bacteria)",
    )
    parser.add_argument(
        "--source",
        choices=("auto", "refseq", "genbank"),
        default="auto",
        help="assembly database to use; auto infers RefSeq for GCF and GenBank for GCA",
    )
    parser.add_argument(
        "--allow-incomplete-accessions",
        action="store_true",
        help="do not preflight file availability or skip accessions missing a requested file",
    )
    parser.add_argument(
        "--skipped",
        type=Path,
        default=Path("download_skipped_accessions.txt"),
        help="output file for accessions skipped because a requested file is unavailable",
    )
    parser.add_argument(
        "--preflight-workers",
        type=int,
        default=4,
        help="number of parallel HEAD checks when validating requested files",
    )
    args = parser.parse_args(argv)

    if not args.gcf or not args.out:
        parser.print_help()
        return 2

    users = read_users(Path(args.gcf).expanduser())
    if not users:
        print(f"ERROR: no GCF/GCA accessions found in {args.gcf}", file=sys.stderr)
        return 1

    sources = determine_sources(list(users), args.source)
    if not sources:
        return 1
    summary_paths = resolve_summary_paths(args.assembly_summary or [], sources)
    if not summary_paths:
        return 1

    if args.download_summary is not None:
        group = args.download_summary or "bacteria"
        for source, summary_path in zip(sources, summary_paths):
            url = f"https://ftp.ncbi.nlm.nih.gov/genomes/{source}/{group}/assembly_summary.txt"
            if not download_summary(url, summary_path.expanduser()):
                return 1

    missing_summaries = [path for path in summary_paths if not path.expanduser().exists()]
    if missing_summaries:
        print("ERROR: summary not found:", *(str(path) for path in missing_summaries), file=sys.stderr)
        print("Run with --download-summary or provide the summary path(s).", file=sys.stderr)
        return 1

    summaries: dict[str, dict[str, str]] = {}
    for path in summary_paths:
        summaries.update(build_summary_dict(path.expanduser()))

    requested_files = parse_file_args(args.files)
    if not requested_files:
        print("ERROR: no requested files.", file=sys.stderr)
        return 1
    wanted = {
        "_" + file_ending if not file_ending.startswith("_") else file_ending
        for file_ending in requested_files
    }

    urls: list[str] = []
    skipped: list[str] = []
    preflight: list[tuple[str, list[str]]] = []
    for acc in sorted(users):
        info = summaries.get(acc.upper())
        ftp_path = (info or {}).get("ftp_path", "")
        if not info:
            skipped.append(f"{acc}\tnot found in selected assembly summary")
            continue
        if not ftp_path:
            skipped.append(f"{acc}\tempty ftp_path in assembly summary")
            continue

        base = ftp_path.rstrip("/").replace(
            "ftp://ftp.ncbi.nlm.nih.gov/",
            "https://ftp.ncbi.nlm.nih.gov/",
        )
        base_name = ftp_path.rstrip("/").split("/")[-1]
        accession_urls = [f"{base}/{base_name}{ending}" for ending in sorted(wanted)]

        if not args.allow_incomplete_accessions:
            preflight.append((acc, accession_urls))
            continue
        urls.extend(accession_urls)

    if preflight:
        worker_count = max(1, args.preflight_workers)
        cache: dict[str, bool] = {}
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = {
                url: pool.submit(url_is_available, url)
                for _, accession_urls in preflight
                for url in accession_urls
            }
            for future in as_completed(futures):
                url = futures[url]
                cache[url] = future.result()

        for acc, accession_urls in preflight:
            missing_files = [
                url.rsplit("/", 1)[-1]
                for url in accession_urls
                if not cache.get(url)
            ]
            if missing_files:
                skipped.append(f"{acc}\tmissing files: {', '.join(missing_files)}")
            else:
                urls.extend(accession_urls)

    if not urls:
        print("ERROR: no complete accessions with downloadable URLs.", file=sys.stderr)
        if skipped:
            write_skipped(skipped, args.skipped.expanduser())
        return 1

    write_urls(sorted(set(urls)), Path(args.out).expanduser())
    write_skipped(skipped, args.skipped.expanduser())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
