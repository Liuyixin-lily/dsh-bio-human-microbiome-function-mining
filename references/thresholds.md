# Default thresholds

Use these defaults unless the user overrides them in `project.json`.

- Sequence identity: >= 0.2 (20%)
- Query coverage fraction: >= 0.7
- E-value: <= 1e-5
- Non-redundant clustering: CD-HIT before DIAMOND makedb. Use 100% identity by
  default when each organism has a single genome; use 95% by default for
  multi-genome pan-proteomes. Users can override with
  `tools.sequence_screen.cdhit_identity` or the wrapper `--cluster-identity`.
- Structure support: TM-score >= 0.5
- Structure quality filter: pLDDT >= 70 where pLDDT is available
- Before structure support, check whether candidate structure files (PDB/CIF)
  exist. If candidate structures are missing, run the bundled
  `structure-prediction` sub-skill (experimental PDB > AlphaFold DB model with
  mean pLDDT >= 60 > homology model > de novo prediction) and continue to
  US-align only after those structures are available.

Thresholds should be stated explicitly in every report so candidates can be
evaluated against the exact policy used.

## Pre-screening ranking (`score_target_priorities.py`)

Both tables are scored on a 0–5 scale per component; every component is filled by a manual cell,
by an `auto:*` derivation, or is `missing` (counted as 0 for the weighted sum, recorded as `missing`
in `score_sources`, never written as a low score).

Enzymes: `priority_score = 0.5 x known + 0.5 x discovery`, both sub-scores on 0–5.

| known (0.5) | weight | discovery (0.5) | weight |
| --- | --- | --- | --- |
| `site_evidence_score` | 0.30 | `microbial_plausibility_score` | 0.40 |
| `disease_relevance_score` | 0.25 | `assay_feasibility_score` | 0.30 |
| `biochemical_clarity_score` | 0.25 | `novelty_score` | 0.30 |
| `sequence_structure_score` | 0.20 | | |

Taxa: `priority_score = sum(weight x component)`, one 0–5 scale, threshold `>= 3.0` selects.

| component | weight |
| --- | --- |
| `site_presence_score` | 0.30 |
| `disease_site_relevance_score` | 0.25 |
| `experimental_accessibility_score` | 0.20 |
| `genome_availability_score` | 0.15 |
| `metabolic_plausibility_score` | 0.10 |

Gates: `--require-min-criteria N` (components with any value) and `--require-min-evidence N`
(components derived from data, `auto:*` only). Rows that fail keep no rank and are written to
`withheld_rows.tsv` with the reason. Weights and the taxa threshold are overridable through
`--config` (`enzyme_known_weight`, `enzyme_discovery_weight`, `taxa_min_priority_score`); a threshold
above the maximum achievable score is rejected instead of silently selecting nothing.
