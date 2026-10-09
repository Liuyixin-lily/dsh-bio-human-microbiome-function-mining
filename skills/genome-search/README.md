# Genome Search

Search NCBI GCF/GCA assemblies for taxa from a source, or audit an existing GCF/GCA list against a source, using Assembly and BioSample metadata.

## Requirements

- Python 3.9+
- `requests`
- `openpyxl` only if writing Excel output

Install dependencies:

```bash
python3 -m pip install requests openpyxl
```

## Taxon-to-genome search

```bash
python3 scripts/genome_source_search.py taxa \
  --input taxa.txt \
  --source skin \
  --out-tsv results/skin_genomes.tsv \
  --out-xlsx results/skin_genomes.xlsx
```

## Accession audit

```bash
python3 scripts/genome_source_search.py accessions \
  --input gcf_gca_list.txt \
  --source oral \
  --out-tsv results/oral_audit.tsv
```

Built-in sources: `skin`, `oral`, `gut`, `respiratory`, `urogenital`, `blood`, `environment`. Custom source terms can be supplied with `--source-file`.

See `SKILL.md` for classification rules and output formats.
