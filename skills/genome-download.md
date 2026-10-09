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
