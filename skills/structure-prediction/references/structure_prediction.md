# Structure prediction reference notes

## Purpose

Turn sequence-only candidates into structure files that US-align can compare
against the reference target structure.

## Default structure priority

1. Experimental PDB.
2. AlphaFold DB model with `mean pLDDT >= 60`.
3. Homology model.
4. De novo prediction.

## Candidate path standard

Final structures must be written as:

```text
structure/<protein_sequence_id>.pdb
```

`protein_sequence_id` is the first whitespace-separated field of the FASTA
header after `>`. Each candidate must have at most one final structure file.

## Database sources

- PDB seqres FASTA:
  <https://files.rcsb.org/pub/pdb/derived_data/pdb_seqres.txt.gz>
- AFDB full-sequence FASTA snapshot:
  <https://ftp.ebi.ac.uk/pub/databases/alphafold/sequences.fasta>

When a local DIAMOND database is absent, the user should build it with
`diamond makedb` after downloading and validating the FASTA file.

## Provenance fields

For each final structure, record:

- `query_sequence_id`
- `source_fasta`
- `structure_source_type`
- `template_or_model_id`
- `method`
- `tool_version`
- `mean_plddt`
- `structure_file`
- `timestamp_or_snapshot`

## Resumability

Skip proteins that already have a valid final structure. Track each query as
`FOUND`, `EXISTS`, `MISSING`, `LOW_QUALITY`, `NO_TEMPLATE`, `PENDING`,
`USER_LIMIT`, or `ERROR`. Keep phase logs append-only and do not restart
completed work.

Use exponential backoff and bounded workers for remote calls. 404 usually
means a missing entry; timeouts, 429, 5xx, and incomplete responses require
retry. Ask before using large thread counts.

## Handoff to US-align

After structure materialization, run:

```bash
python3 human_microbiome_function_mining/scripts/run_usalign.py \
  --project project.json
```

Do not US-align structures that did not pass the quality gate for their
source type.
