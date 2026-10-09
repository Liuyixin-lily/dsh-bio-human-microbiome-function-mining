#!/usr/bin/env python3
"""Download NCBI genome URLs into species-named folders.

Example:
  python3 download_genomes.py \
    --metadata metadata.txt \
    --urls download_urls.txt \
    --out .
"""

from __future__ import annotations

import argparse
import gzip
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def gunzip_file(path: Path) -> Path:
    """Decompress a gzip file to the same path without the .gz suffix.

    Falls back to plain subprocess gunzip if a gzip error occurs.
    """
    out = path.with_suffix("")
    tmp = out.with_suffix(out.suffix + ".gunzip.tmp")
    try:
        with gzip.open(path, "rb") as src, tmp.open("wb") as dst:
            shutil.copyfileobj(src, dst)
        tmp.replace(out)
        path.unlink()
    except (OSError, gzip.BadGzipFile):
        if tmp.exists():
            tmp.unlink()
        gunzip = shutil.which("gunzip") or "gunzip"
        result = subprocess.run([gunzip, "-f", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode != 0:
            raise RuntimeError(f"gunzip failed for {path}")
    return out


def canonical_file_name(name: str) -> str:
    """Return an accession-based output filename for a standard NCBI genome file."""
    archive = name.endswith(".gz")
    stem = name[:-3] if archive else name
    match = re.match(r"^(GCF|GCA)_\d+\.\d+_", stem, flags=re.IGNORECASE)
    if not match:
        return name

    accession = match.group(0)[:-1]
    remainder = stem[match.end():]
    if remainder.endswith("_cds_from_genomic.fna"):
        suffix = "_genomic.ffn"
    else:
        for suffix in ("_genomic.fna", "_protein.faa", "_genomic.gbff", "_genomic.gff", "_genomic.ffn"):
            if remainder.endswith(suffix):
                break
        else:
            return name
    return f"{accession}{suffix}{'.gz' if archive else ''}"


def normalize_file_name(path: Path) -> Path:
    """Rename a downloaded or unpacked NCBI file to its accession-based name."""
    new = path.with_name(canonical_file_name(path.name))
    if new == path:
        return path
    new.parent.mkdir(parents=True, exist_ok=True)
    path.replace(new)
    return new


def is_gzip(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(2) == b"\x1f\x8b"
    except OSError:
        return False


def is_completed_download(path: Path) -> bool:
    """Return True when a gzip archive exists and has no aria2 control file."""
    return (
        path.exists()
        and path.stat().st_size > 0
        and is_gzip(path)
        and not path.with_name(path.name + ".aria2").exists()
    )


def unpack_and_rename(target: Path) -> None:
    """Validate, decompress, and normalize one downloaded genome archive."""
    unpacked = gunzip_file(target)
    normalize_file_name(unpacked)


def read_metadata(metadata_path: Path) -> dict[str, str]:
    """Return accession -> safe folder name from species/GCF or species/GCA tables."""
    out: dict[str, str] = {}
    with metadata_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2:
                continue
            if parts[0].strip().upper().startswith(("GCF", "GCA")):
                acc = parts[0].strip().upper()
                sp = parts[1].strip()
            elif parts[1].strip().upper().startswith(("GCF", "GCA")):
                sp = parts[0].strip()
                acc = parts[1].strip().upper()
            else:
                continue
            sp = sp.replace(" ", "_").replace("/", "_").strip()
            out[acc] = sp
    return out


def accession_from_filename(name: str) -> str:
    # NCBI basename: GCF_000160795.1_ASM16079v1_cds_from_genomic.fna.gz
    fields = name.split("_")
    return "_".join(fields[:2]).upper()


def download_url(url: str, target: Path, tries: int = 5, decompress: bool = False) -> bool:
    """Download one URL with curl, using resumable partial transfers."""
    curl = shutil.which("curl") or "curl"
    tmp = target.with_suffix(target.suffix + ".tmp")
    for _ in range(tries):
        try:
            if tmp.exists() and (tmp.stat().st_size == 0 or not is_gzip(tmp)):
                tmp.unlink()
            cmd = [
                curl,
                "-fsS",
                "-A",
                "Mozilla/5.0",
                "--connect-timeout",
                "25",
                "--speed-limit",
                "1024",
                "--speed-time",
                "60",
                "-C",
                "-",
                "-o",
                str(tmp),
                url,
            ]
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode == 0 and tmp.stat().st_size > 0 and is_gzip(tmp):
                tmp.replace(target)
                if decompress:
                    unpacked = gunzip_file(target)
                    normalize_file_name(unpacked)
                return True
            if tmp.exists():
                tmp.unlink()
        except (OSError, subprocess.SubprocessError):
            pass
        time.sleep(5)
    return False


def run_aria2c(tasks: list[tuple[str, Path]], args) -> dict[tuple[str, Path], bool]:
    """Run aria2c over the URL list and report whether each task completed."""
    aria2 = shutil.which("aria2c")
    if not aria2:
        return {(url, target): False for url, target in tasks}

    input_path = tasks[0][1].parent / "download_urls.aria2.txt"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    with input_path.open("w", encoding="utf-8") as fh:
        for url, target in tasks:
            fh.write(url + "\n")
            fh.write(f"  dir={target.parent}\n")
            fh.write(f"  out={target.name}\n\n")

    cmd = [
        aria2,
        "--input-file",
        str(input_path),
        "--concurrent-downloads",
        str(args.jobs),
        "--max-connection-per-server",
        str(args.connections_per_server),
        "--split",
        str(args.split),
        "--min-split-size",
        "10M",
        "--continue=true",
        "--file-allocation=none",
        "--max-tries",
        str(args.tries),
        "--retry-wait=5",
        "--connect-timeout",
        "30",
        "--timeout",
        "120",
        "--summary-interval=10",
        "--download-result=hide",
        "--console-log-level=warn",
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"WARNING: aria2c exited with status {result.returncode}", file=sys.stderr)

    outcomes: dict[tuple[str, Path], bool] = {}
    for url, target in tasks:
        outcomes[(url, target)] = is_completed_download(target)
    input_path.unlink(missing_ok=True)
    return outcomes


def download_parallel_curl(
    tasks: list[tuple[str, Path]], tries: int, jobs: int
) -> dict[tuple[str, Path], bool]:
    """Run curl in a bounded thread pool for systems without aria2c."""
    outcomes: dict[tuple[str, Path], bool] = {}
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = {
            pool.submit(download_url, url, target, tries, False): (url, target)
            for url, target in tasks
        }
        for future in as_completed(futures):
            task = futures[future]
            try:
                outcomes[task] = future.result()
            except Exception:
                outcomes[task] = False
    return outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", required=True, help="TSV with species and GCF/GCA accession")
    parser.add_argument("--urls", required=True, help="URL list from build_download_links.py")
    parser.add_argument("--out", default=".", help="base output directory")
    parser.add_argument("--tries", type=int, default=5, help="download attempts per URL")
    parser.add_argument(
        "--decompress",
        action="store_true",
        help="decompress .gz files after download and remove the .gz archive",
    )
    parser.add_argument(
        "--downloader",
        choices=("auto", "aria2c", "curl"),
        default="auto",
        help="download engine; auto uses aria2c when available",
    )
    parser.add_argument("--jobs", type=int, default=4, help="concurrent downloads")
    parser.add_argument(
        "--connections-per-server",
        type=int,
        default=2,
        help="aria2c connections per server",
    )
    parser.add_argument(
        "--split",
        type=int,
        default=4,
        help="aria2c splits per file",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    folder_by_acc = read_metadata(Path(args.metadata).expanduser())
    if not folder_by_acc:
        print("ERROR: no GCF/GCA accessions found in metadata file", file=sys.stderr)
        return 1

    urls = Path(args.urls).expanduser().read_text(encoding="utf-8").splitlines()
    urls = [u.strip() for u in urls if u.strip()]
    if not urls:
        print("ERROR: URL list is empty", file=sys.stderr)
        return 1

    fail_path = out_dir / "download_failures.txt"
    log_path = out_dir / "download_progress.log"
    if fail_path.exists():
        fail_path.unlink()

    done = 0
    fails = 0
    tasks: list[tuple[str, Path]] = []
    use_aria2c = args.downloader == "aria2c" or (
        args.downloader == "auto" and shutil.which("aria2c") is not None
    )

    for url in urls:
        name = url.rstrip("/").split("/")[-1]
        acc = accession_from_filename(name)
        folder_name = folder_by_acc.get(acc)
        if not folder_name:
            fails += 1
            with fail_path.open("a", encoding="utf-8") as fh:
                fh.write(f"{name} => no metadata match for {acc}\n")
            continue

        target = out_dir / folder_name / canonical_file_name(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if is_completed_download(target):
            if args.decompress:
                try:
                    unpack_and_rename(target)
                    done += 1
                except (OSError, RuntimeError):
                    fails += 1
                    with fail_path.open("a", encoding="utf-8") as fh:
                        fh.write(url + "\n")
            else:
                done += 1
        elif args.decompress and target.with_suffix("").exists() and target.with_suffix("").stat().st_size > 0:
            normalize_file_name(target.with_suffix(""))
            done += 1
        else:
            tasks.append((url, target))

    if tasks:
        if use_aria2c:
            outcomes = run_aria2c(tasks, args)
        else:
            outcomes = download_parallel_curl(tasks, args.tries, args.jobs)

        for (url, target), ok in sorted(outcomes.items()):
            if not ok:
                fails += 1
                with fail_path.open("a", encoding="utf-8") as fh:
                    fh.write(url + "\n")
                continue
            if args.decompress:
                try:
                    unpack_and_rename(target)
                    done += 1
                except (OSError, RuntimeError):
                    fails += 1
                    with fail_path.open("a", encoding="utf-8") as fh:
                        fh.write(url + "\n")
            else:
                done += 1

    line = f"DONE got={done} fails={fails}"
    print(line, flush=True)
    log_path.write_text(line + "\n", encoding="utf-8")

    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
