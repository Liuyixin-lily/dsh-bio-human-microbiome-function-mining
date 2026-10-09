# Genome Annotation

Batch annotate bacterial genomes with Bakta using a full or light local database.

## Requirements

- Linux server or workstation with `bash`
- Bakta installed in a conda environment
- Bakta full or light database downloaded locally
- Dependencies used by Bakta: `tRNAscan-SE`, Prodigal/Prokka dependencies, etc.
  are handled by the Bakta conda environment

## Environment variables

| Variable | Use |
| --- | --- |
| `BAKTA_BIN_DIR` | Directory containing the `bakta` executable |
| `BAKTA_DB_FULL` | Path to the Bakta full database |
| `BAKTA_DB_LIGHT` | Path to the Bakta light database |

## Install Bakta

```bash
conda create -n bakta -c conda-forge -c bioconda bakta
conda activate bakta
```

Download the Bakta database according to the Bakta manual. A common layout is:

```text
<your_bakta_db>/
  bakta.db
  ...
```

Then export the path before running:

```bash
export BAKTA_BIN_DIR=/path/to/conda/envs/bakta/bin
export BAKTA_DB_FULL=/path/to/bakta/db/full
export BAKTA_DB_LIGHT=/path/to/bakta/db/light
```

## Run

```bash
bash scripts/bakta_batch.sh \
  --indir /data/genomes \
  --outdir /data/annotations \
  --db full \
  --threads 16
```

For a direct database path:

```bash
bash scripts/bakta_batch.sh \
  --indir /data/genomes \
  --outdir /data/annotations \
  --db-path /path/to/generated-db \
  --threads 16
```

See `SKILL.md` for full options.
