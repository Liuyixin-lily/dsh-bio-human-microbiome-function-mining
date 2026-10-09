# DIAMOND Sequence Screening Reference

This is the standalone reference for enumerating candidate microbial proteins
with sequence similarity to a host enzyme.

## Context

This skill was split out from `skin-microbiome-pipeline` Phase 3:

- Phase 0: enzyme discovery and ranking
- Phase 1: prepare and download GCF protein data
- Phase 2: build pan-proteome / CD-HIT dedup
- Phase 3: DIAMOND sequence screening
- Phase 4-7c: structure-based downstream filtering and ranking

The pan-proteome input is expected to come from Phase 2. The hits produced here
are sequence evidence for later structural alignment filtering.

## Workflow rules inherited from the parent pipeline

- Run DIAMOND sequence search against the pan-proteome.
- Before `makedb`, deduplicate the candidate proteome with CD-HIT. Use 100%
  identity when each organism has a single genome; use 95% for multi-genome
  pan-proteomes unless the user overrides it in `project.json` or with
  `--cluster-identity`.
- Keep hits with identity `>= 20%` and query coverage `>= 0.7`.
- Zero hits are acceptable for divergent families.
- DIAMOND must still be run to preserve the evidence trail.

## Exact filter semantics

In `run_diamond_screening.sh`, the DIAMOND column order is:

```text
qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore qcovhsp
```

The filter keeps rows where:

```text
pident >= --identity
qcovhsp >= --coverage
```

## Run examples

Build and search in one command:

```bash
bash human_microbiome_function_mining/skills/screen-sequence-candidates/scripts/run_diamond_screening.sh \
  --query host_enzyme.faa \
  --db panproteome.faa \
  --outdir sequence_screening \
  --identity 20 \
  --coverage 0.707 \
  --threads 16
```

Search with a prebuilt database:

```bash
bash human_microbiome_function_mining/skills/screen-sequence-candidates/scripts/run_diamond_screening.sh \
  --query host_enzyme.faa \
  --dmnd panproteome.dmnd \
  --outdir sequence_screening
```

## Output files

- `diamond_hits.m8`: raw DIAMOND tabular output.
- `diamond_hits.tsv`: m8 results with a TSV header.
- `diamond_hits.filtered.tsv`: m8 results passing identity and coverage cutoffs.
- `diamond_summary.txt`: input paths, threshold values, and hit counts.
- `panproteome.dmnd`: generated when a FASTA is supplied with `--db`.

## Direct DIAMOND commands

Equivalent manual commands:

```bash
diamond makedb \
  --in panproteome.faa \
  --db panproteome.dmnd \
  --threads 16
```

```bash
diamond blastp \
  --query host_enzyme.faa \
  --db panproteome.dmnd \
  --out diamond_hits.m8 \
  --outfmt 6 qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore qcovhsp \
  --evalue 1e-5 \
  --threads 16 \
  --max-target-seqs 50000
```

## Downstream use

The hits are sequence evidence only. Candidate proteins that pass conventional
sequence thresholds may still be filtered out later if their structures do not
align to the template host enzyme. Conversely, divergent sequences can become
interesting if their predicted structures align well with the host enzyme.
