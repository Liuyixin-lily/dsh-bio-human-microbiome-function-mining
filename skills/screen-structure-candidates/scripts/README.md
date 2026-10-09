# Structure Screening Scripts

- `run_usalign_screening.sh`: local US-align runner that writes
  `structural_hits.tsv` and `structural_candidates.tsv`.

Before running US-align, confirm that candidate structure files (PDB/CIF)
exist for the sequence-filtered candidates. If a candidate lacks a structure,
run the bundled `structure-prediction` sub-skill (experimental PDB > AlphaFold
DB model passing `mean pLDDT >= 60` > homology model > de novo) and continue
only after the returned structures are materialized as
`structure/<protein_sequence_id>.pdb`.

DEER is a fallback only. It should be attempted only when US-align produces
insufficient suitable candidates and the user agrees. DEER output can be added
as extra structure evidence rows, but it never replaces US-align as the primary
structural screen.
