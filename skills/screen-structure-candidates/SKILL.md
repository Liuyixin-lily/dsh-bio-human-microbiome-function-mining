---
name: screen-structure-candidates
description: >-
  Screen candidate protein structures against a reference target structure. First check whether candidate structure files exist and, if they are missing, run the bundled structure-prediction sub-skill. Then use US-align directly on all available candidate structure files, and try DEER only when US-align yields no qualifying candidate for a genome, or not enough of them.
metadata:
  short-description: Rank candidates by structural alignment
---

# Screen Structure Candidates

Use this skill when sequence candidates exist and the workflow needs
structure-supported candidates before final evidence integration. This skill
runs between `screen-sequence-candidates` and `merge-candidate-evidence`.

Tool boundary: this sub-skill can run US-align through
`scripts/run_usalign.py` and DEER through `scripts/run_deer.py` when the
configured executables and structure files are accessible from the current
terminal and `auto_run_local` is enabled. Otherwise Agent gives the user the
exact command and consumes the returned output files. DEER remains a fallback
only and is attempted only when US-align yields none or does not produce enough suitable
candidates and the user agrees.

## Principle

Structural screening is organized as a decision chain, not a set of parallel
equivalent options:

1. Check whether candidate structure files (PDB or CIF) exist for the
   sequence-filtered candidates.
2. If candidates lack structure files, run the bundled `structure-prediction`
   sub-skill to retrieve known structures or predict missing structures.
   Priority for final structures:
   experimental PDB > AlphaFold DB model passing `mean pLDDT >= 60` >
   homology model > de novo prediction. Only continue after the candidate
   structures are materialized as `structure/<protein_sequence_id>.pdb`.
3. Run **US-align** directly against the reference target structure for every
   available candidate structure file.
4. Keep US-align-passing candidates as structure-supported evidence.
5. **Only if US-align yields no qualifying candidate at all for a genome, or
   does not produce enough suitable candidates for that genome**, try **DEER**
   to retrieve additional structure-based candidates. Also apply DEER as a
   whole-study fallback when the merged sequence+structure candidate list
   contains no qualifying candidate at all.
6. Do not claim a structural hit as functional proof. All outputs are hypotheses
   for later candidate scoring and experimental validation.

Foldseek is not the default route for this plugin. If Foldseek is already
available and the user explicitly requests large-scale pre-screening before
US-align, it may be used as an optional prefilter, but US-align remains the
primary structural evidence.

## Inputs

Required inputs:

- Reference target structure file (PDB or CIF).
- Candidate structure directory or individual candidate structure files.

Optional inputs:

- TM-score threshold.
- DEER candidate cutoff.
- User-provided existing US-align or DEER output files.

## Workflow

1. Read `sequence_candidates.tsv` from the sequence screening step and the
   user-supplied candidate structure files or structure directory.
2. Check whether candidate structure files exist for the sequence-filtered
   candidates. If they are missing, run the bundled `structure-prediction`
   sub-skill to obtain or predict structures.
   Recommended structure priority:

   1. experimental PDB structure for the candidate protein if available;
   2. AlphaFold DB model passing `mean pLDDT >= 60`;
   3. homology model;
   4. de novo prediction.

   After the user returns the structures, and only then, proceed to US-align.
3. Instruct the user to run US-align directly against the reference target
   structure for every candidate structure file:

   ```bash
   bash human_microbiome_function_mining/skills/screen-structure-candidates/scripts/run_usalign_screening.sh \
     --target references/target_structure.pdb \
     --candidate-dir outputs/structure/candidate_structures/ \
     --outdir outputs/structure
   ```

   The wrapper writes `structural_hits.tsv` and `structural_candidates.tsv`
   through `scripts/parse_usalign.py`.

4. Keep candidates with USalign TM-score >= 0.5 unless the user overrides the
   threshold in their project config.
5. Write `structural_hits.tsv` for the full US-align alignment table. Keep
   structure support as `1` only when the configured TM-score threshold is met.
6. Write `structural_candidates.tsv` as the complete structure-supported
   candidate list, not only rescued proteins.
7. If US-align cannot find enough suitable candidates for a genome, ask the user
   to confirm the fallback. Then run DEER for that genome through the wrapper
   when available:

   ```bash
   python3 human_microbiome_function_mining/scripts/run_deer.py \
     --project project.json \
     --template-dir inputs/target_structures \
     --candidate-dir outputs/structure/candidate_structures \
     --outdir outputs/alignments/deer
   ```

   The wrapper reads `candidate_sequences.genomes` from the project config,
   detects which source genomes have zero US-align structural candidates, and
   triggers DEER only for those genomes. It refuses to run when no US-align
   output is visible unless the user explicitly passes
   `--allow-without-usalign`. Install DEER only after that fallback is agreed:

   ```bash
   git clone https://github.com/WangJiuming/deer.git
   cd deer
   conda env create --name deer --file env/env_cpu.yml
   conda activate deer
   ```

   Run retrieval on the candidate structures:

   ```bash
   CUDA_VISIBLE_DEVICES="" python do_retrieval.py \
     --template_pdb_dir /path/to/template_pdb/ \
     --database_pdb_dir /path/to/candidate_pdb/ \
     --output_dir /path/to/output
   ```

   Record DEER output as additional structure-based evidence only. DEER must
   not replace US-align and must not be run before US-align has been attempted
   or before the user agrees that the US-align result is insufficient.
8. Map catalytic residues and compare active pockets when the user supplies
   catalytic residue data for the target.

## Output schema

Write machine-readable structure evidence according to:

- `schemas/structural_hits.schema.tsv`
- `schemas/structural_candidates.schema.tsv`

Required output files:

- `structural_hits.tsv`: US-align alignment table and any DEER evidence mapped
  into the same structure-evidence format.
- `structural_candidates.tsv`: ranked candidates supported by structure
  evidence.

Preserve tool names, versions, and source file paths. If a candidate has both
US-align and DEER evidence, record both sources in the row provenance.

Scripts:

- `scripts/run_usalign_screening.sh`: local US-align runner and TSV parser wrapper.
- `scripts/parse_usalign.py`: shared US-align text-to-TSV parser (also used directly by the example test).
- `scripts/run_deer.py`: gated fallback runner for DEER retrieval. It parses
  DEER `similarity.csv` into `structural_candidates.tsv` through
  `scripts/parse_deer.py` when the retrieval completes locally.

## Default thresholds

- Structure support: TM-score >= 0.5.
- Structure quality filter: pLDDT >= 70 where pLDDT is available.
- Missing-structure fallback: use the bundled `structure-prediction` sub-skill
  (experimental PDB > AlphaFold DB model with `mean pLDDT >= 60` > homology
  model > de novo prediction) before running US-align.

State the thresholds and the exact tool versions used in the task report.

## Guardrails

- Do not skip US-align for any candidate structure file supplied by the user.
- Do not treat DEER distance and US-align TM-score as directly comparable.
- Do not claim that a structure-supported candidate is a confirmed enzyme.
- Do not fabricate US-align or DEER output. If one tool is not available or has
  not been run, say so and mark that evidence as pending.
