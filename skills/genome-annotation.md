---
name: genome-annotation
description: >-
  Annotate bacterial genomes with Bakta using a full or light local database;
  default to the full database when not specified.
language: mixed
category: guide
---

# Genome Annotation

Use this skill when the user wants to run Bakta genome annotation on a batch of
FASTA genome files, or package/adapt the Bakta annotation workflow for a local
or shared compute server.

## Database Selection

Ask or infer the database explicitly only when it changes the command
meaningfully. Default to the full database if the user does not say otherwise.

- Full database, default:
  - config value: `full`
  - path from env `BAKTA_DB_FULL`, or override with `--db-path`
- Light database:
  - config value: `light`
  - path from env `BAKTA_DB_LIGHT`, or override with `--db-path`

If neither environment variable is set and no `--db-path` is supplied, the
script fails with a clear message instead of assuming a server-specific path.

## Batch Input and Output

The helper script accepts a directory containing `.fa` or `.fna` genome files
and creates one output directory per genome under the output root, using the
original filename without extension. Result files are also named with the
original genome filename first, for example `SAMPLENAME.gff3`,
`SAMPLENAME.tsv`, and `SAMPLENAME.json`. Sequence and feature IDs in the text
outputs are rewritten to use the original sample name as their prefix, for
example `SAMPLENAME_00001`.

```bash
bash /path/to/human_microbiome_function_mining/scripts/bakta_batch.sh \
  --indir /data/genomes \
  --outdir /data/annotations \
  --db full \
  --threads 16
```

Useful flags:

- `--indir`: input directory of genome FASTA files (`*.fa`, `*.fna`).
- `--outdir`: output root directory.
- `--db full|light`: select the database path from `BAKTA_DB_FULL` or
  `BAKTA_DB_LIGHT`.
- `--db-path PATH`: use a direct Bakta database path, overriding `--db`.
- `--threads N`: Bakta threads per genome.
- `--mode ser|par`: `ser` runs one genome at a time; `par` runs up to
  `--par-jobs` concurrent genomes.
- `--par-jobs N`: number of concurrent Bakta jobs when `--mode par`.
- `--prefix-tag`: optional string used to build short Bakta internal
  prefixes/locus tags.
- `--force`: overwrite an existing genome output directory.
- `--log`: log file path.

Set these environment variables before running the helper:

| Variable | Use |
| --- | --- |
| `BAKTA_BIN_DIR` | Directory containing the `bakta` executable |
| `BAKTA_DB_FULL` | Path to the Bakta full database |
| `BAKTA_DB_LIGHT` | Path to the Bakta light database |

Alternatively pass `--db-path PATH` for a custom Bakta database path.

## Guardrails

- If Bakta is not accessible, give the user the exact command and wait for
  returned annotation output.
- Do not invent annotation fields. Preserve the original Bakta output paths and
  tool version.
