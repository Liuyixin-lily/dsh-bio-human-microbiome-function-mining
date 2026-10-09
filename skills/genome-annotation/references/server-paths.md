# Bakta Environment and Database Setup

Use this file when adapting the Bakta annotation workflow to a new machine.
None of the paths below are required; they are examples only.

## Environment variables

The helper script reads these environment variables:

| Variable | Meaning | Example |
| --- | --- | --- |
| `BAKTA_BIN_DIR` | Directory that contains the `bakta` executable | `/home/you/miniconda3/envs/bakta/bin` |
| `BAKTA_DB_FULL` | Path to the Bakta full database | `/data/bakta/db` |
| `BAKTA_DB_LIGHT` | Path to the Bakta light database | `/data/bakta/db-light` |

You can also pass `--db-path /path/to/db` directly instead of setting
`BAKTA_DB_FULL` or `BAKTA_DB_LIGHT`.

## Verifying a Bakta installation

```bash
export BAKTA_BIN_DIR=/path/to/envs/bakta/bin
"$BAKTA_BIN_DIR/bakta" --version
find "$BAKTA_DB_FULL" -maxdepth 1 -type d | head
```

Bakta needs helper binaries such as `tRNAscan-SE` on `PATH`. Prefer exporting
the active environment `bin` directory, or use the absolute `bakta` binary.

## Example run on a new machine

```bash
export BAKTA_BIN_DIR=/home/you/miniconda3/envs/bakta/bin
export BAKTA_DB_FULL=/data/bakta/db
export BAKTA_DB_LIGHT=/data/bakta/db-light

bash /path/to/skill/scripts/bakta_batch.sh \
  --indir /data/genomes \
  --outdir /data/annotations \
  --db full \
  --threads 16
```

Or with a direct database path:

```bash
bash /path/to/skill/scripts/bakta_batch.sh \
  --indir /data/genomes \
  --outdir /data/annotations \
  --db-path /data/bakta/custom-db \
  --threads 16
```

Do not assume any specific NCBI dataset, input path, or shared server layout.
