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
