---
name: structure-prediction
description: >-
  Retrieve, model, or predict protein structures for candidate protein
  sequences using PDB, AlphaFold DB, homology modeling, or a user-specified
  predictor, with pLDDT confidence filtering and resumable processing.
metadata:
  short-description: Obtain candidate protein structures before US-align
---

# Structure Prediction

Use this skill when candidate proteins have sequence evidence but lack a
materialized PDB or mmCIF structure file. This skill runs inside the
`functional-dark-matter-discover` workflow before `screen-structure-candidates`
and US-align.

## Workflow

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

## Running the workflow

The Agent runs the lookup, download, and modeling steps directly only when the
executable and database paths in `project.json` are readable from the current
terminal and `auto_run_local` is enabled. Otherwise the Agent gives the exact
commands for the user's compute environment and waits for returned structure
files.

Default command patterns are documented in
`skills/structure-prediction.md`:

- PDB template search and direct download.
- AlphaFold DB sequence search and direct AFDB model download.
- Homology modeling with MODELLER or an equivalent user-supplied tool.
- De novo prediction only after explicit user choice.

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

## Quality gates

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

## Downstream

After structures are available, run US-align through
`scripts/run_usalign.py`. Only structure files that passed the quality gate
for the candidate and source type should become `structural_hits.tsv` or
`structural_candidates.tsv`.

## Guardrails

- Do not fabricate PDB entries, AlphaFold IDs, models, or pLDDT values.
- Do not route low-quality structures into downstream candidates.
- Do not run US-align before candidate structures materialize.
- Do not infer biochemical activity from predicted structures alone.
- Do not run de novo prediction unless the user picks the method and provides
  the executable or environment.
