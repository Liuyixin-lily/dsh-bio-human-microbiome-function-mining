---
name: sequence-mapping
description: >-
  Run DIAMOND sequence screening for host-like enzyme discovery against a
  pan-proteome. Use when the user wants to identify candidate microbial proteins
  by sequence similarity from skin microbiome or other metagenome pan-proteomes.
---

# Sequence Mapping

Use this skill when the user wants sequence-based screening of candidate enzymes,
especially the Phase 3 DIAMOND screening step from a microbiome enzyme-mining
pipeline.

## Purpose

Run DIAMOND sequence search for a template host enzyme against a pan-proteome,
then keep high-confidence hits for downstream structural screening, catalytic
residue mapping, or candidate ranking.

## Inputs

Required inputs:

- Query FASTA containing the host enzyme protein sequence.
- A pan-proteome FASTA to search, or a prebuilt DIAMOND database.

Optional inputs:

- Identity threshold.
- Query coverage threshold.
- E-value threshold.

## Run the workflow

The core runner is `scripts/run_diamond_screening.sh` and the wrapper is
`scripts/run_diamond.py`.

## CD-HIT deduplication

Before building a DIAMOND database, deduplicate the candidate proteome with
CD-HIT. The default identity is:

- 100% when each organism is represented by a single genome.
- 95% when the candidate set is a multi-genome pan-proteome.

Set `tools.sequence_screen.cdhit_identity` in `project.json` or pass
`--cluster-identity` to `scripts/run_diamond.py` to override. Pass
`--cluster-identity 0` to skip CD-HIT when the input FASTA is already
non-redundant.

Build a DIAMOND database and screen in one step:

```bash
bash human_microbiome_function_mining/skills/screen-sequence-candidates/scripts/run_diamond_screening.sh \
  --query host_enzyme.faa \
  --db panproteome.faa \
  --outdir sequence_screening \
  --identity 20 \
  --coverage 0.7 \
  --threads 16
```

Or use a prebuilt database:

```bash
bash human_microbiome_function_mining/skills/screen-sequence-candidates/scripts/run_diamond_screening.sh \
  --query host_enzyme.faa \
  --dmnd panproteome.dmnd \
  --outdir sequence_screening
```

## Default thresholds

| Parameter | Default | Meaning |
| --- | --- | --- |
| `--identity` | `20` | Minimum percent identity |
| `--coverage` | `0.7` | Minimum query coverage fraction, from `qcovhsp` |
| `--evalue` | `1e-5` | Maximum E-value |
| `--threads` | `SLURM_CPUS_PER_TASK` or `8` | Threads for build and search |
| `--max-target-seqs` | `50000` | Max alignments returned per query |

The pipeline-level rule from the parent workflow is to keep hits with identity
`>= 0.2` and coverage `>= 0.7`.

## Outputs

| File | Content |
| --- | --- |
| `diamond_hits.m8` | Raw DIAMOND tabular output |
| `diamond_hits.tsv` | Same hits with a readable header |
| `diamond_hits.filtered.tsv` | Hits passing identity and coverage thresholds |
| `diamond_summary.txt` | Run parameters and hit counts |
| `panproteome.dmnd` | DIAMOND database when built from `--db` |

## Practical notes

- Zero hits can be acceptable for divergent enzyme families, but DIAMOND should
  still be run to preserve the evidence trail.
- For large searches, increase `--threads` and consider using a prebuilt
  `--dmnd` database.
- The downstream pipeline uses these hits as sequence evidence before structural
  alignment.

Detailed reference notes are in `references/diamond_screening.md`.
