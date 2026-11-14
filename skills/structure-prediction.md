---
name: structure-prediction
description: >-
  Retrieve known protein structures or predict missing candidate structures
  for sequence candidates, using PDB, AlphaFold DB, homology modeling, or a
  user-specified predictor, with pLDDT quality gates and structured outputs.
language: mixed
category: protocol
---

# Structure Prediction

Use this skill when candidate proteins have sequence evidence but lack a
materialized PDB or mmCIF structure file. It must run before US-align when the
user does not already supply candidate structure files.

**Tool boundary**: this plugin does not bundle PDB/AFDB downloads, DIAMOND,
ColabFold/ESMFold, or MODELLER. The Agent runs the workflow when the user
supplies tool executables, database paths, and an accessible compute
environment. Otherwise the Agent gives exact commands and waits for returned
structure files.

## When to use

- `screen-sequence-candidates` produced hits with no existing `.pdb`/`.cif` file.
- The user asks how to obtain structures for a set of candidate proteins.
- The pipeline needs `structure/<protein_sequence_id>.pdb` before US-align.

## Input

- Candidate protein FASTA files (one or more `.faa` files).
- Optional local databases:
  - PDB sequence FASTA / DIAMOND database (for template search).
  - AlphaFold DB full-sequence FASTA / DIAMOND database (for direct AFDB retrieval).
- Optional method choice from the user: `pdb`, `afdb`, `homology`, `de_novo`,
  or a user-specified predictor.

## Output

Write one final structure per protein when possible:

```text
structure/<protein_sequence_id>.pdb
```

Use the first whitespace-separated field of the FASTA header as
`protein_sequence_id`. Do not leave partially written structures in the final
directory; write atomically then move into place. Record provenance for every
final structure:

- query sequence id
- source FASTA path
- source type (`PDB`, `AFDB`, `homology`, `de_novo`)
- template/model id when relevant
- method and tool version
- `mean_plddt` when available
- output path
- run timestamp or source snapshot date

## Structure priority

Prefer known and higher-quality structures in this order:

1. Experimental PDB structure for the candidate protein if available.
2. AlphaFold DB model passing `mean pLDDT >= 60`.
3. Homology model.
4. De novo prediction (for example ESMFold/ColabFold only when no higher
   priority source is available).

Apply the same priority to reference target structures.

## Missing public download access

If the current terminal cannot access PDB or AlphaFold DB endpoints, do not
fabricate structures. Give the user the exact commands for a machine or server
with network access and wait for returned files. When the user provides local
PDB/AFDB database paths that are readable from the current terminal, the Agent
may run the lookup/download steps directly.

## Running the workflow

### Option A: existing PDB download

When PDB seqres FASTA or a PDB DIAMOND database is available, search candidate
sequences against PDB with DIAMOND, classify hits, and download direct PDB
chains:

```bash
diamond blastp --ultra-sensitive --query-cover 50 --subject-cover 50 --id 50 \
  --query candidate_proteins.faa --db /path/to/pdb.dmnd \
  --out pdb_hits.tsv --outfmt 6 \
  qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore qlen slen \
  --threads 16 --max-target-seqs 200
```

Download the matching chains from RCSB:

```bash
python3 skills/structure-prediction/scripts/download_pdb_direct.py
```

If the user does not have local PDB database files, they can download the
official PDB seqres FASTA from RCSB before building a DIAMOND database:

```text
https://files.rcsb.org/pub/pdb/derived_data/pdb_seqres.txt.gz
```

### Option B: direct AlphaFold DB retrieval

Use the AFDB sequence search route when the AFDB full-sequence FASTA / DIAMOND
database is configured and the user wants to avoid expensive de novo prediction:

```bash
diamond blastp --ultra-sensitive --query-cover 50 --subject-cover 50 --id 50 \
  --query candidate_proteins.faa --db /path/to/afdb.dmnd \
  --out afdb_hits.tsv --outfmt 6 \
  qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore qlen slen \
  --threads 16 --max-target-seqs 200
```

Download direct AFDB models from the returned `pdbUrl`, then run the AFDB
quality gate. Reject models with mean pLDDT below 60 and quarantine them
instead of treating them as valid structure evidence.

Official AFDB full-sequence FASTA source:

```text
https://ftp.ebi.ac.uk/pub/databases/alphafold/sequences.fasta
```

### Option C: homology modeling

For candidate proteins with PDB or AFDB direct hits but no final structure,
build a homology-model manifest after direct downloads are complete:

```bash
python3 skills/structure-prediction/scripts/build_homology_pending.py
python3 skills/structure-prediction/scripts/run_homology_modeling.py \
  --manifest homology_pending.tsv --threads 6
```

Do not invent template identities. Only run homology modeling when the user
has MODELLER or an equivalent tool installed and the manifest lists a valid
template.

### Option D: user-specified de novo predictor

For candidates with no known structure and no homology template, only run de
novo prediction after the user explicitly chooses the method and provides the
executable/environment. Record the tool name, version, model used, and the
resulting pLDDT/confidence metric.

## Quality and resumability

- Skip proteins that already have a valid non-empty final structure file.
- Log each phase as `FOUND`, `EXISTS`, `MISSING`, `LOW_QUALITY`,
  `NO_TEMPLATE`, `PENDING`, `USER_LIMIT`, or `ERROR` with reason.
- Separate permanent nonexistence from transient failures. 404 usually means
  missing entry; timeouts, 429, 5xx, and incomplete responses require retry.
- Use bounded workers and exponential backoff for remote APIs. Respect the
  user's server load and thread limits.
- Rebuild DIAMOND databases only when missing, unreadable, stale, or requested.
- Finish with a per-file/per-species summary: known structures found,
  predicted structures, and still-missing structures.

## Downstream integration

After structure materialization, continue with:

```bash
python3 human_microbiome_function_mining/scripts/run_usalign.py \
  --project project.json
```

Only US-align candidate structure files that passed the structure-quality gate
for their source type. Do not route low-quality models into downstream
structural candidates.

The bundled pipeline entry point is
`skills/structure-prediction/scripts/run_structure_pipeline.sh`. See the script
header for the required `STRUCTURE_PRED_ROOT`, PDB/AFDB database, and model
source arguments. Detailed reference notes are in
`skills/structure-prediction/references/structure_prediction.md`.

## Inventory and triage before any retrieval

0. **Inventory supplied structures first. Do not fetch or predict what the user
   already provided.** For every query, check in this order:
   - the path(s) the user supplied (target structure, candidate structure
     directory, `project.json` structure settings);
   - an already-materialized `structure/<protein_sequence_id>.pdb`.

   Classify each query as `EXISTS` (final structure already present, including a
   user-supplied model), `FOUND` (retrieved from PDB/AFDB), `MISSING` (needs
   prediction), or `LOW_QUALITY`. Process **only** `MISSING` and `LOW_QUALITY`
   entries with the remaining steps. `EXISTS` entries are used as-is: no
   retrieval, no prediction, no overwrite. Report the classification counts so
   it is visible which work was actually necessary.

1. Read configured structure-prediction settings from `project.json`:
   `tools.structure_prediction`. Honor `enabled`, `auto_run_local`,
   `executable`, and `output_dir` when present.
2. Ask the user which structure route to use when the target is unclear:
   experimental PDB, AlphaFold DB, homology model, or de novo prediction.
3. Use PDB/AFDB retrieval first, then homology modeling, then de novo
   prediction. Do not skip a lower-quality method to a higher one.
4. Enforce the AFDB quality gate: direct AFDB models must pass
   `mean pLDDT >= 60`. Screen out and quarantine lower-quality models.
5. For every protein, write at most one final structure:
   `structure/<protein_sequence_id>.pdb`.
6. Write a per-species/per-file summary of found, predicted, and missing
   structures.
7. Record provenance for every final structure, including query ID, source
   FASTA, source type, template/model ID, method, tool version, pLDDT, and
   output path.

## Input and output conventions

- Input is one or more non-empty protein FASTA files. Include every normal
  `.faa` file; do not silently include Bakta-style `*.hypotheticals.faa` files
  unless the user confirms the target proteins may be hypothetical.
- `protein_sequence_id` is the first whitespace-separated field of the FASTA
  header after `>`.
- Resolve duplicate FASTA ids before starting.
- Write temporary files atomically and move them into the final structure
  path. Never leave empty or partial `.pdb` files in final directories.
- Preserve original FASTA identifiers in all mapping, hit, candidate, and
  provenance tables.

## Acceptance criteria for a usable structure

- Experimental PDB structure: accepted if the chain matches the candidate.
- Direct AFDB model: accepted only when `mean pLDDT >= 60`.
- Homology model: require a valid template, identity/coverage when available,
  and record the model quality metric.
- De novo model: record the tool, version, and confidence metric
  (for example ESMFold pLDDT or AlphaFold PAE).

## Missing data

Do not claim a candidate has a structure when it does not. Report per-candidate
status: `FOUND`, `EXISTS`, `MISSING`, `LOW_QUALITY`, `NO_TEMPLATE`, `PENDING`,
`USER_LIMIT`, or `ERROR`. If the current terminal lacks network access or user
database paths, say what external command is needed and wait for returned
files.

## Guardrails

- Do not fabricate PDB entries, AlphaFold IDs, models, or pLDDT values.
- Do not route low-quality structures into downstream candidates.
- Do not run US-align before candidate structures materialize.
- Do not infer biochemical activity from predicted structures alone.
- Do not run de novo prediction unless the user picks the method and provides
  the executable or environment.
