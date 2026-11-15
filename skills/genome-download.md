---
name: genome-download
description: >-
  Batch-download NCBI RefSeq/GCF or GenBank/GCA genomes from a species list or
  accession list. Use when the user needs genomic.fna.gz, protein.faa.gz,
  cds_from_genomic.fna.gz, genomic.gbff.gz, or genomic.gff.gz files for many
  genomes.
language: mixed
category: guide
---

# Genome Download

This skill maps species names to NCBI assemblies, or accepts a user-provided
`GCF`/`GCA` list, then downloads the standard genome file set into
species-named folders inside the requested output directory. It resolves FTP
paths from the correct NCBI `assembly_summary.txt`, preflights requested files
with parallel HEAD checks, uses resumable/parallel downloads, and can
decompress files immediately.

## Inputs

The skill accepts one of these:

- A species name list, one scientific name per line. Blank lines and comments
  are ignored.
- A `GCF`/`GCA` accession list, one accession per line, or a TSV with an
  `assembly_accession` column.
- A `metadata.txt`-style table with `species<TAB>accession` or
  `accession<TAB>species`.

When metadata provides a species name, that name is the source of truth for
the output folder. Convert spaces and `/` to underscores, for example
`Acinetobacter calcoaceticus` becomes `Acinetobacter_calcoaceticus`.

## Step 1: Build the accession list

For a species-name input, query NCBI Datasets:

```bash
python3 human_microbiome_function_mining/scripts/build_gcf_list.py \
  --species species.txt \
  --out accessions.tsv \
  --assembly-level chromosome,complete,scaffold
```

RefSeq/`GCF` is the default. Use `--genbank` when the user explicitly asks for
GenBank/`GCA` assemblies.

For a manual `GCF`/`GCA` list, normalize it without querying NCBI:

```bash
python3 human_microbiome_function_mining/scripts/build_gcf_list.py --manual accessions.txt --out accessions.tsv
```

## Step 2: Resolve summaries and preflight files

`GCF` accessions use the RefSeq summary. `GCA` accessions use the GenBank
summary. Mixed lists use both summaries; the source order is always RefSeq then
GenBank.

For a bacteria-only list:

```bash
python3 human_microbiome_function_mining/scripts/build_download_links.py \
  --download-summary bacteria \
  --gcf accessions.tsv \
  --out download_urls.txt \
  --skipped download_skipped_accessions.txt \
  --preflight-workers 4
```

For another biological group, replace `bacteria` with the matching group such
as `fungi`, `archaea`, `protozoa`, `viral`, `plant`,
`vertebrate_mammalian`, `vertebrate_other`, or `invertebrate`.

The default requested file set is exactly:

```text
*_genomic.fna.gz
*_protein.faa.gz
*_cds_from_genomic.fna.gz
*_genomic.gbff.gz
*_genomic.gff.gz
```

Before writing the URL list, the builder checks that every requested file
exists for each accession. If an accession lacks any requested file, the whole
accession is skipped and recorded in `download_skipped_accessions.txt`. Use
`--files` when the user requests a different file set. The same
all-or-none preflight applies.

For slow remote-server transfers, download the assembly summary locally, upload
the complete file, and rerun with explicit `--assembly-summary` paths.

## Step 3: Download into species folders

```bash
python3 human_microbiome_function_mining/scripts/download_genomes.py \
  --metadata metadata.txt \
  --urls download_urls.txt \
  --out /path/to/output \
  --decompress \
  --downloader auto \
  --jobs 4 \
  --connections-per-server 2 \
  --split 4
```

The downloader prefers `aria2c` when it is installed and otherwise falls back
to bounded parallel curl downloads. Both paths use resumable transfers.

## Practical rules

- Prefer RefSeq/`GCF` unless the user explicitly requests GenBank/`GCA`.
- Skip an accession and record it when it is absent from the selected summary,
  has an empty FTP path, or lacks any requested standard file.
- Keep downloads in per-species folders named from the metadata species name.
- After decompression, verify each complete species folder has `genomic.fna`,
  `protein.faa`, `genomic.ffn`, `genomic.gbff`, and `genomic.gff`, with no
  `.gz` or `.tmp` residue.

## References

- [scripts/build_gcf_list.py](scripts/build_gcf_list.py): species/taxon to `GCF`/`GCA` accession-list builder.
- [scripts/build_download_links.py](scripts/build_download_links.py): accession list to NCBI URL builder with parallel complete-file preflight.
- [scripts/download_genomes.py](scripts/download_genomes.py): downloader with parallel retries, resume, gzip validation, species folders, and decompression.
- [references/assembly-summary.md](references/assembly-summary.md): where NCBI keeps each `assembly_summary.txt`, which columns matter, and how the two groups differ when a list mixes RefSeq and GenBank.

### Slow-summary fallback

For a remote-server run, first try the normal `--download-summary` flow. If the server-to-NCBI transfer is stalled or clearly slow, stop that command and transfer a complete summary from the local machine instead:

```bash
# Run locally. For a mixed list, fetch both summaries.
curl -fL --retry 5 --retry-delay 5 --connect-timeout 30 \
  -o /tmp/ncbi_assembly_summary_refseq.txt \
  https://ftp.ncbi.nlm.nih.gov/genomes/refseq/bacteria/assembly_summary.txt

curl -fL --retry 5 --retry-delay 5 --connect-timeout 30 \
  -o /tmp/ncbi_assembly_summary_genbank.txt \
  https://ftp.ncbi.nlm.nih.gov/genomes/genbank/bacteria/assembly_summary.txt
```

Confirm that each local file is non-empty and ends cleanly before uploading. Then transfer the complete files to the server:

```bash
scp -o ConnectTimeout=30 /tmp/ncbi_assembly_summary_refseq.txt \
  user@server:/work/ncbi_assembly_summary_refseq.txt
scp -o ConnectTimeout=30 /tmp/ncbi_assembly_summary_genbank.txt \
  user@server:/work/ncbi_assembly_summary_genbank.txt
```

On the server, use the explicit `--assembly-summary` form and omit `--download-summary` so the builder does not retry the slow NCBI transfer:

```bash
python3 scripts/build_download_links.py \
  --gcf accessions.tsv \
  --assembly-summary ncbi_assembly_summary_refseq.txt \
  --assembly-summary ncbi_assembly_summary_genbank.txt \
  --out download_urls.txt \
  --skipped download_skipped_accessions.txt
```

Provide summaries in RefSeq-then-GenBank order for mixed lists. For a single-source list, provide only the matching summary and replace `bacteria` with the correct biological group when downloading locally.

For a mixed `GCF`/`GCA` list with summaries already available, use the offline-summary form in RefSeq-then-GenBank order:

```bash
python3 scripts/build_download_links.py \
  --gcf accessions.tsv \
  --assembly-summary ncbi_assembly_summary_refseq.txt \
  --assembly-summary ncbi_assembly_summary_genbank.txt \
  --out download_urls.txt \
  --skipped download_skipped_accessions.txt
```

The default requested file set is exactly:

```text
*_genomic.fna.gz
*_protein.faa.gz
*_cds_from_genomic.fna.gz
*_genomic.gbff.gz
*_genomic.gff.gz
```

Before writing the URL list, the builder checks that every requested file exists for each accession. If an accession lacks any one of the requested files, the entire accession is skipped so no partial folder is created. The accession and missing file names are recorded in `download_skipped_accessions.txt`. This is the default behavior; `--allow-incomplete-accessions` exists only as an explicit override.

Use `--files` when the user requests a different file set. The same all-or-none preflight applies to that requested set.
