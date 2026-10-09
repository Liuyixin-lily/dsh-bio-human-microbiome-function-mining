# Genome Download

Batch-download NCBI RefSeq/GCF or GenBank/GCA genomes from a species list or an accession list.

## Requirements

- Python 3.9+
- Network access to NCBI
- `curl`
- Optional: `aria2c` for faster parallel downloads

## Quick start

Build a GCF/GCA accessions TSV from a species list:

```bash
python3 scripts/build_gcf_list.py \
  --species species.txt \
  --out accessions.tsv \
  --assembly-level chromosome,complete,scaffold
```

Or normalize a manual GCF/GCA list:

```bash
python3 scripts/build_gcf_list.py --manual accessions.txt --out accessions.tsv
```

Resolve download links from the correct NCBI assembly summary:

```bash
python3 scripts/build_download_links.py \
  --download-summary bacteria \
  --gcf accessions.tsv \
  --out download_urls.txt \
  --skipped download_skipped_accessions.txt
```

Download into species folders:

```bash
python3 scripts/download_genomes.py \
  --metadata metadata.txt \
  --urls download_urls.txt \
  --out /path/to/output \
  --decompress \
  --downloader auto \
  --jobs 4
```

See `SKILL.md` for full options and offline-summary fallback flow.
