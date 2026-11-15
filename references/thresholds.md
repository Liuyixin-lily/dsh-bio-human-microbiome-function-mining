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
| `site_evidence_score` | 0.25 | `microbial_plausibility_score` | 0.40 |
| `disease_relevance_score` | 0.25 | `assay_feasibility_score` | 0.30 |
| `biochemical_clarity_score` | 0.25 | `novelty_score` | 0.30 |
| `sequence_structure_score` | 0.25 | | |

The four known dimensions are weighted equally on purpose: niche evidence, human-health relevance,
biochemical characterisation and sequence/structure data are four dimensions of the same question, and
equal weights say none is privileged a priori. The cost of that choice is worth stating: the score
difference between two candidates is exactly `0.025 x (structure - site evidence)`, so a candidate with a
structure but no literature can tie one with literature but no structure. `config.ranking.site-heavy.json`
restores the previous 0.30 / 0.25 / 0.25 / 0.20 profile, and `config.ranking.equal-weights.json` spells
the current default out as a file you can diff.

Taxa: `priority_score = sum(weight x component)`, one 0–5 scale, threshold `>= 3.0` selects. The
recommended-taxa table is exactly the `selected` rows; rows below the threshold stay in the full table
as `defer`. Enzymes have no pass mark - their recommended table is the ranked rows with at least two
scored components, since too few components are derivable before screening for a fixed cut-off to leave
anything.

| component | weight |
| --- | --- |
| `site_presence_score` | 0.30 |
| `disease_site_relevance_score` | 0.25 |
| `experimental_accessibility_score` | 0.20 |
| `genome_availability_score` | 0.15 |
| `metabolic_plausibility_score` | 0.10 |

Where a taxa component comes from, without a genome-search run: `site_presence` from the species list's
measured abundance, `genome_availability` from the list's `recommended_strain_count`, `metabolic_plausibility`
from the library's `focus_taxa`, and `disease_site_relevance` from a literature table plus `--disease`
(two verified rows mentioning the phenotype = 4, one = 3, verified but none = 1 "searched, no evidence").
Every component now has a derivation, and each one records which input produced it
(`auto:library` / `auto:registry` / `auto:taxa_list` / `auto:genome_search` / `auto:literature[:assay|:cultivation|:no_match]`):

| component | table | derived from |
| --- | --- | --- |
| `site_evidence` | enzyme | verified functional records: 1=3, 2=4, >=3=5; review only=2 |
| `disease_relevance` | enzyme | verified records matching `--disease`: >=2=4, 1=3, none=1 |
| `biochemical_clarity` | enzyme | EC confidence + reaction + substrate/product + fold hint |
| `sequence_structure` | enzyme | reference set: structure=5, accession only=3 |
| `microbial_plausibility` | enzyme | known microbial examples: 0=1, 1=3, >=2=4; or a registry's `microbial_context` |
| `novelty` | enzyme | dark matter=5, no examples=4, examples=2 |
| `assay_feasibility` | enzyme | verified records naming an assay/method: >=2=4, 1=3; a functional record without method words=3 |
| `site_presence` | taxa | genome-search direct ratio, else the species list's measured abundance |
| `genome_availability` | taxa | genome-search assembly count, else the list's `recommended_strain_count` |
| `metabolic_plausibility` | taxa | the library's `focus_taxa` attention |
| `disease_site_relevance` | taxa | verified records matching `--disease`: >=2=4, 1=3, none=1 |
| `experimental_accessibility` | taxa | verified isolation/culture records: >=2=4, 1=3; a sequenced isolate alone=2 |

Filling them is a step, not a hope: `scripts/literature_for_registry.py --registry <registry.tsv>
--site <site> --output literature_evidence.tsv` retrieves per candidate and writes the table the ranker
consumes. With that table plus `--reference-enzymes` (for `sequence_structure`) every component of a
candidate that has an EC gets a value. A candidate with no EC cannot get a reference set, so
`sequence_structure` stays `missing` there — that is a real gap, not a hidden low score, and
`--require-min-criteria` will withhold the row if it matters.

A phenotype component (`disease_relevance_score`, `disease_site_relevance_score`) is only asked when
`--disease` is given. Without it the component is recorded as `not_applicable`, dropped from the
weighted sum, and the remaining weights renormalise; a component nobody asked about must not count as
either evidence or a gap.

What literature cannot settle is stated rather than scored: biosafety level, equipment cost and
per-assay turnaround are not derived, so the report never implies them. A component with no supporting
evidence stays `missing` (counted as 0 in the weighted sum, labelled `missing` in `score_sources`) —
absence of evidence is not a low score.

Gates: `--require-min-criteria N` (components with any value) and `--require-min-evidence N`
(components derived from data, `auto:*` only). Rows that fail keep no rank and are written to
`withheld_rows.tsv` with the reason. Weights and the taxa threshold are overridable through
`--config` (`enzyme_known_weight`, `enzyme_discovery_weight`, `taxa_min_priority_score`); a threshold
above the maximum achievable score is rejected instead of silently selecting nothing.
