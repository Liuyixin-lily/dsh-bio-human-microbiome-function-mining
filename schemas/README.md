# Schemas

This directory defines machine-readable contracts for plugin outputs. DeepSeek
must follow these schemas when writing new task files.

## Files

- `target_function_card.schema.json`: target function normalization.
- `reference_enzyme_set.schema.tsv`: loaded reference enzyme table.
- `sequence_hits.schema.tsv`: sequence screening output.
- `structural_hits.schema.tsv`: structure screening / alignment output.
- `sequence_candidates.schema.tsv`: candidates supported by sequence evidence.
- `structural_candidates.schema.tsv`: candidates supported by structure evidence.
- `source_feature_annotations.schema.tsv`: existing annotations parsed from user-provided `.faa` or `.gbff` files.
- `combined_candidates.schema.tsv`: final integrated candidate ranking.
- `experimental_hypotheses.schema.tsv`: falsifiable experimental hypotheses
  generated from each scored candidate, including mechanistic model, critical
  experiments, falsification criteria, ambient/alternative hypothesis,
  evidence chain, and verified literature citations.

The combined table can merge orthogonal validation results such as FedKEA
enzyme identification / EC number prediction. FedKEA fields are prefixed with
`fedkea_` and must be traceable to the original FedKEA output file.

Existing source-file annotations from FASTA headers and GenBank CDS features can
be merged as another evidence chain. These fields are prefixed with `source_`
or stored in `existing_annotation`, and must be traceable to the original
`.faa`/`.gbff` file path.

Schema files distinguish required columns from columns that are "Optional but
recommended". Evidence-specific columns such as `tm_score_mean`,
`sequence_score`, `sequence_rank`, `catalytic_score`,
`genome_context_score`, `ecological_score`, `assembly_accession`, and
`fedkea_*` are recommended but may legitimately be empty when the corresponding
evidence source does not exist for a row. `priority_tier` is produced later by
`scripts/score_candidates.py` on the combined table; in pre-scoring
`sequence_candidates.tsv` and `structural_candidates.tsv` files it is optional.

Expected FedKEA source files:

- `binary_result.txt`
- `enzyme_result_with_probability.csv`
- `enzyme_result_with_confidence.csv`

## Rule

Every generated TSV must include at least the columns listed in its schema.
Additional columns are allowed only when they preserve provenance and are
explained in the report. Do not rename or omit standard columns.

Final delivery summaries written by `scripts/summarize_candidates.py`
(`high_confidence_candidate_summary.tsv` and `final_target_candidates.tsv`) are
compact project-facing views of `scored_candidates_full.tsv`, not replacements
for the full evidence-table contracts documented here. The same script also
writes `experimental_hypotheses.tsv` until the Agent finalizes
`experimental_design.md` from literature and the user's assay context.
