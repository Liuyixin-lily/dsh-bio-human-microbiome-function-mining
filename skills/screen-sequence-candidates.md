---
name: screen-sequence-candidates
description: >-
  Run or consume DIAMOND sequence screening for candidate microbial proteins,
  including CD-HIT deduplication before search.
language: mixed
category: protocol
---

# Screen Sequence Candidates

Use this skill when the workflow needs sequence-based screening of candidate
enzymes against a human microbiome pan-proteome. This skill covers CD-HIT
deduplication and DIAMOND sequence search, then keeps high-confidence hits for
downstream structural screening or candidate scoring. CD-HIT identity defaults
to 100% for single-genome datasets and 95% for multi-genome pan-proteomes.

## Inputs

Required inputs:

- Query FASTA containing the target host enzyme protein sequence.
- A candidate proteome FASTA to search, or a prebuilt DIAMOND database.

Optional inputs:

- Identity threshold.
- Query coverage threshold.
- E-value threshold.

## Run the workflow

The core runner is `scripts/run_diamond.py`, which performs CD-HIT
deduplication before building the DIAMOND database and screening. Set
`tools.sequence_screen.cdhit_identity` in `project.json` or pass
`--cluster-identity` to override.

```bash
python3 human_microbiome_function_mining/scripts/run_diamond.py \
  --project project.json
```

Or use the shell helper for a more direct invocation:

```bash
bash human_microbiome_function_mining/skills/screen-sequence-candidates/scripts/run_diamond_screening.sh \
  --query host_enzyme.faa \
  --db panproteome.faa \
  --outdir sequence_screening \
  --identity 20 \
  --coverage 0.7 \
  --threads 16
```

Use a prebuilt database with `--dmnd`.

## Default thresholds

| Parameter | Default | Meaning |
| --- | --- | --- |
| `--identity` | `20` | Minimum percent identity |
| `--coverage` | `0.7` | Minimum query coverage fraction, from `qcovhsp` |
| `--evalue` | `1e-5` | Maximum E-value |
| `--threads` | `SLURM_CPUS_PER_TASK` or `8` | Threads for build and search |
| `--max-target-seqs` | `50000` | Max alignments returned per query |

The pipeline rule is to keep hits with identity `>= 0.2` and query coverage
`>= 0.7`, unless the user overrides these thresholds.

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
- If the DIAMOND executable or database is not accessible from the current
  terminal, give the user the exact command and wait for returned output.

Detailed reference notes are in
`skills/screen-sequence-candidates/references/diamond_screening.md`.
