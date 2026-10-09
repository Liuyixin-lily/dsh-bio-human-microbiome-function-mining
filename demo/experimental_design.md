# Experimental Design

This document is the plugin-consistent entry point for the wet-lab validation
plan of the two high-confidence neutral sphingomyelinase candidates.

- Final high-confidence candidate table: `final_target_candidates.tsv`
- Evidence summary: `high_confidence_candidate_summary.tsv`

Minimum required experiments:

1. Clone each candidate CDS into a recombinant expression vector.
2. Express and purify each protein, with empty vector as a negative control.
3. Run at least one coupled fluorogenic SMase assay plus one orthogonal product
   detection method, for example NBD-C6-sphingomyelin and TLC/fluorescence.
4. Include positive control, empty-vector control, and heat-inactivated
   control in every run.
5. Repeat with independent replicates; compare wild-type with predicted
   catalytic-site mutants if active-site residues are mapped.

Go/no-go:

- Go: reproducible sphingomyelin hydrolysis activity above at least 2-3x the
  negative control, with orthogonal product detection and positive control
  behaving correctly.
- No-go: no reproducible activity above background, or activity traceable to a
  contaminating enzyme rather than the recombinant protein.

No claim of confirmed enzyme function may be made before these experiments are
performed and independently repeatable.
