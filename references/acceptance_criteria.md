# Acceptance Criteria for a Task Run

Before closing a task, confirm every machine-readable output exists and is
traceable back to a source file or command the user supplied.

## Required files

- `target_function_card.json`
- `sequence_hits.tsv` and `sequence_candidates.tsv` if sequence screening ran
- `structural_hits.tsv` and `structural_candidates.tsv` if US-align/DEER output
  was provided
- `combined_candidates.tsv` with at least one candidate row and provenance
- `scored_candidates_full.tsv` with `overall_rank`, `priority_rule`,
  `priority_order`, and `rank_policy`
- `high_confidence_candidate_summary.tsv`
- `final_target_candidates.tsv` when at least one row meets the selected
  `--final-rules`
- `experimental_hypotheses.tsv` with one falsifiable hypothesis per scored
  candidate
- `experimental_design.md`

## Provenance checks

- Every candidate row has a `candidate_id` and `protein_accession`.
- `provenance` names the source tables that contributed to the row.
- Any `fedkea_*` field has an original FedKEA file path and tool version.
- FedKEA was run on the candidate subset submitted for validation, not silently
  on the full proteome, unless the user explicitly requested a whole-proteome
  scan and the report says so.
- FedKEA output accessions were checked against the expected candidate IDs.
  Zero overlap is a failed validation step; partial mismatch is recorded in
  `fedkea_notes` before any FedKEA field is used in scoring.
- Any `source_*` field has the original `.faa`/`.gbff` file path and feature
  type recorded in `source_annotation_note`.
- No PDB, UniProt, PubMed, EC, KEGG, Pfam, or GO identifier is fabricated.
- Each high-confidence candidate has an explicit falsifiable hypothesis
  statement, testable prediction, critical experiments, and falsification
  criteria. Strain-specific transformation, vector, knockout efficiency
  validation, and assay details must be traceable to verified literature or
  the user's stated assay/system context, not invented by the Agent.

## Tool boundaries

- Agent did not claim to run FedKEA, DEER, or US-align unless the user supplied
  the tool output.
- For any tool that has not run yet, the task report says exactly which command
  the user should execute and which output files to return.
- DEER was used as a fallback only after US-align was attempted or explicitly
  decided to be skipped with the user's agreement.
- When the DEER fallback gate is triggered (a genome has no qualifying US-align
  candidate, or the merged candidate list has no qualifying candidate) but the
  DEER software/checkpoint has not been made available, the task report
  explicitly records `DEER status: pending` and prints the exact `do_retrieval.py`
  command the user needs to run. It must not imply that DEER was already
  attempted or completed.

## Scientific interpretation

- Structure-only hits are marked as hypotheses.
- FedKEA EC predictions are marked as additional validation.
- Existing `.faa`/`.gbff` annotations are marked as existing-knowledge evidence.
  A DIAMOND hit whose existing annotation matches the target EC or enzyme
  name/product synonym is marked `SEQUENCE_ANNOTATION_CONFIRMED` and skips
  structure screening.
- No row claims confirmed biochemical function without experimental evidence.

## Scoring

- `overall_rank` is controlled by the explicit `priority_rule` /
  `priority_order` assigned by `scripts/score_candidates.py`, not by a hidden
  weighted `overall_score`. `overall_score` is retained only as a
  backward-compatible display value and does not control final order.
- The priority order is `SEQUENCE_ANNOTATION_CONFIRMED`, `USALIGN_TARGET_EC`,
  `DEER_FEDKEA_CONFIRMED`, `USALIGN_OTHER_EC`, `USALIGN_NOT_ENZYME`,
  `USALIGN_UNVALIDATED`, `DEER_FALLBACK`, `SEQUENCE_ONLY`, `ANNOTATION_ONLY`.
- Default ranking is TM-score-first: rows carrying a TM-score are ordered by it
  descending, and rows without one follow, ordered among themselves by
  `priority_order`, then `sequence_score` descending, then annotation strength
  descending, then `candidate_id` ascending. `--rank-by priority` selects the
  tier-first ordering instead, and `rank_policy` must record which mode was used.
- When `--target-ec` is supplied, FedKEA rows matching the target EC are
  upgraded to `USALIGN_TARGET_EC`; non-matching EC rows become
  `USALIGN_OTHER_EC`.
- DEER rows with FedKEA enzyme confirmation are upgraded to
  `DEER_FEDKEA_CONFIRMED`, which ranks above `USALIGN_OTHER_EC`.
- `overall_score` weights are stated in the task report.
- Sequence and structural scores do not mix with FedKEA or source annotation
  scores in the priority sort except for the documented tie-break order.
