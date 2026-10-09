# Genome Dataset Preparation

Use this optional preparation layer when the user does not already have a
candidate proteome or annotated candidate genomes.

The plugin ships three sub-skills:

- `skills/genome-search/`: map taxa or an existing `GCF`/`GCA` list to NCBI
  assemblies that have source metadata matching `skin`, `oral`, `gut`,
  `respiratory`, `urogenital`, `blood`, or `environment`.
- `skills/genome-download/`: batch-download standard NCBI genome files into
  species-named folders, keeping `genomic.fna`, `protein.faa`, `genomic.ffn`,
  `genomic.gbff`, and `genomic.gff`.
- `skills/genome-annotation/`: run Bakta on genome FASTA files that lack
  annotations so the plugin can extract protein/CDS evidence from `.gbff` or
  annotated `.faa` outputs.

## When to use

Ask which input the user has before starting the main workflow:

1. Already has a candidate proteome `.faa` and/or `.gbff`: skip this layer and
   continue to sequence screening.
2. Has taxa, source, or `GCF`/`GCA` accessions but no candidate dataset: run
   the three sub-skills in order.
3. Has genomes but no protein files or annotations: run only
   `genome-annotation`.

Apply the same execution rule as other external tools: when the relevant
scripts and NCBI access are reachable from the current terminal, run them
directly; otherwise give the user the exact commands and wait for returned
files.

## Output layout expected by the plugin

Place prepared files where `project.json`/`config.example.json` points:

```text
databases/genomes/<species>/
  genomic.fna
  protein.faa
  genomic.ffn
  genomic.gbff
  genomic.gff
```

The candidate proteome for DIAMOND screening can be either the concatenated
`protein.faa` files or the user's existing `candidate_proteome.faa`. The
annotated `.gbff`/`.faa` files feed `parse_source_annotations.py` so existing
protein/CDS annotations become a `source_feature_annotations.tsv` evidence
chain.

## Provenance

Keep these bookkeeping files:

- `genome_search_results.tsv`
- `genome_accessions.tsv`
- `download_urls.txt`
- `download_skipped_accessions.txt`
- Bakta run logs and database version

Preserve them so candidate provenance can be traced back to NCBI accession,
downloaded URL, and annotation tool version.
