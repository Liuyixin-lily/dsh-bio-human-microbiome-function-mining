---
name: genome-search
description: >-
  Search NCBI GCF/GCA assemblies for taxa from a specified source, or audit an
  existing GCF/GCA list against a specified source, using Assembly and
  BioSample metadata.
language: mixed
category: guide
---

# Genome Search

Use this skill when the user needs one of two NCBI workflows:

1. **Taxon-to-genomes search**: given microbe taxa and a source such as skin,
   oral, gut, respiratory, blood, urine, or environment, find matching
   GCF/GCA assemblies.
2. **Accession audit**: given a GCF/GCA list, determine whether each assembly
   has metadata supporting the requested source.

## Core workflow

Use the bundled script for reproducible searches:

```bash
python3 human_microbiome_function_mining/scripts/genome_source_search.py taxa \
  --input taxa.txt \
  --source skin \
  --out-xlsx results/skin_genomes.xlsx \
  --out-tsv results/skin_genomes.tsv
```

```bash
python3 human_microbiome_function_mining/scripts/genome_source_search.py accessions \
  --input gcf_gca_list.txt \
  --source oral \
  --out-xlsx results/oral_audit.xlsx \
  --out-tsv results/oral_audit.tsv
```

The script can accept one or more built-in source names (`skin`, `oral`,
`gut`, `respiratory`, `urogenital`, `blood`, `environment`) or a
comma-separated custom term list. A custom source file can be supplied with
`--source-file`.

## Important behavior

- Always resolve assemblies through **Assembly + BioSample**, not through
  Assembly metadata alone. BioSample frequently contains the true
  `isolation_source`, `body_site`, or `tissue` evidence that Assembly summaries
  omit.
- Report evidence explicitly. Do not infer source from taxonomy alone unless
  the user asks for ecological association rather than direct source metadata.
- In accession-audit mode, classify as:
  - `Direct source match`: BioSample/Assembly source fields contain requested
    terms.
  - `Source metadata present, no match`: source metadata exists but lacks
    requested terms.
  - `No source metadata`: no usable source fields were returned.
  - `Assembly not found`: NCBI did not return the exact accession.
- Preserve BioSample accession, source fields, matched terms, organism,
  assembly accession, and BioProject in the output.
- For large lists, use caching and process in batches. Respect NCBI rate limits
  and retry transient 429/5xx errors.

## Excel output

When writing an Excel file, create at least these sheets:

- `All assemblies`: full record-level results.
- `Summary`: counts and percentages by classification.
- `Direct_source_matches`: only rows whose source metadata contains requested
  terms.

If some input accessions cannot be resolved, add a `Missing_assemblies` sheet.
