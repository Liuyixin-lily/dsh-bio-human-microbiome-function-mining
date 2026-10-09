# Scripts

Reusable local parsers used by the plugin skills.

Available scripts:

- `build_target_function_card.py`: writes a normalized target function card from enzyme metadata.
- `fetch_reference_enzymes.py`: fetches reference enzyme records from NCBI
  Protein and RCSB PDB by enzyme name, EC number, organism, and PDB IDs, then
  writes `reference_enzyme_set.tsv`, `reference_enzymes.faa`, and
  `reference_provenance.json`. When `--project project.json` is set, the
  script also reads the `reference_enzyme` config block for query terms and
  relative output paths. It also picks one primary reference record (PDB
  structure first, then UniProt/NCBI annotation, then first record) and tries
  to download its local sequence/structure files under
  `<reference_output_dir>/reference_enzymes/`, recording the result in
  `primary_reference.json`.
- `parse_sequence_hits.py`: converts DIAMOND-style TSV output to `sequence_hits.tsv` and `sequence_candidates.tsv`.
- `parse_usalign.py`: parses USalign `-outfmt 2` text into `structural_hits.tsv` and `structural_candidates.tsv`.
- `prep_usalign_parallel.py`: writes chunk/split launcher files for running
  US-align over remaining candidate PDB/CIF structures in an isolated
  acceptance directory. It is an internal parallel-run utility and is not part
  of the normal single-terminal workflow.
- `parse_fedkea.py`: parses user-supplied FedKEA output files into `fedkea_results.tsv`.
- `parse_deer.py`: parses DEER `similarity.csv` into a plugin-compatible
  structural evidence table, keeping the raw DEER distance/rank in dedicated
  fields rather than treating that metric as a TM-score. Pass
  `--candidate-dir` plus `--source-genomes` when the candidate structure
  directory contains per-genome symlinks so each DEER hit is mapped to its
  actual source genome.
- `parse_source_annotations.py`: parses existing `.faa` header annotations and `.gbff` CDS annotations into `source_feature_annotations.tsv`.
- `merge_candidates.py`: merges sequence, structure, FedKEA, and existing
  source annotations into `combined_candidates.tsv`. Pass `--project
  project.json` when the project JSON records `candidate_sequences.candidates`
  source genome paths; missing `organism_or_strain` and `assembly_accession`
  values are filled from that metadata instead of remaining blank.
- `score_candidates.py`: assigns deterministic `overall_score`, `overall_rank`,
  `priority_tier`, `priority_rule`, and `priority_order` to the combined table
  using the explicit structure-first priority rules documented in the script
  and in `schemas/combined_candidates.schema.tsv`. Pass `--target-ec` to match
  the configured target EC inside `USALIGN_TARGET_EC`. DEER candidates that
  FedKEA confirms as enzymes are placed in `DEER_FEDKEA_CONFIRMED`, above
  `USALIGN_OTHER_EC`.
- `summarize_candidates.py`: reads `scored_candidates_full.tsv`, optional
  `candidate_gene_evidence.tsv`, and an optional project JSON, then writes
  `high_confidence_candidate_summary.tsv` (all scored rows with validation
  verdicts), `final_target_candidates.tsv` (the rows matching
  `--final-rules`, default `USALIGN_TARGET_EC`), and
  `experimental_hypotheses.tsv` (one falsifiable hypothesis per scored
  candidate) in `--outdir`. Pass `--literature` to merge verified
  `literature_evidence.tsv` into candidate hypothesis tables.
- `validate_schema.py`: checks output TSVs against `schemas/*.schema.tsv`
  contracts. By default it verifies that required schema columns are present
  in headers and reports empty required cells as warnings; pass
  `--require-nonempty` to turn empty required cells into hard errors.
- `example_test.py`: end-to-end example test against small synthetic inputs.
  It validates parser, merge, and scoring scripts without depending on real
  DIAMOND, US-align, DEER, or FedKEA executions.

Agent-runnable wrappers:

- `run_diamond.py`: runs configured CD-HIT deduplication on the candidate
  proteome, then DIAMOND screening when executable/data are accessible, then
  calls `parse_sequence_hits.py`. Derived from the `sequence-mapping` runner.
  CD-HIT identity defaults to 1.0 for single-genome datasets and 0.95 for
  multi-genome pan-proteomes; set `tools.sequence_screen.cdhit_identity` or
  pass `--cluster-identity` to override. Pass `--cluster-identity 0` to skip
  CD-HIT when the input FASTA is already non-redundant.
- `run_usalign.py`: runs configured US-align when executable/structures are
  accessible, then calls `parse_usalign.py`. Derived from the
  `structure-mapping` US-align route.
- `run_deer.py`: runs DEER retrieval only after visible US-align evidence or an
  explicit user-approved override; otherwise writes a pending checkpoint with
  the exact DEER command. When DEER completes and writes `similarity.csv`, it
  automatically calls `parse_deer.py` for the same genome. Supports
  `--top-k`, `--tmp-dir`, and `--distance-cutoff` to match `do_retrieval.py`
  and the parsing cutoff.
- `run_bakta.py`: runs the bundled `genome-annotation/bakta_batch.sh` when the
  Bakta environment is accessible, otherwise writes a pending checkpoint.
- `run_fedkea.py`: runs the configured local FEDKEA `main.py` when accessible,
  then calls `parse_fedkea.py`. When not accessible, writes a pending
  checkpoint with the exact `main.py` command and never calls the FedKEA web
  server programmatically.

Skill-local launchers:

- `skills/screen-sequence-candidates/scripts/run_diamond_screening.sh`
- `skills/screen-structure-candidates/scripts/run_usalign_screening.sh`

The plugin does not ship a generic Runner. It can run configured external tools
directly when their executables and inputs are accessible from the current
terminal and `auto_run_local` is enabled. Otherwise the user supplies their own
dataset and runs external tools on their own compute; these scripts parse and
merge the evidence tables the user produces.

Literature evidence is deliberately not script-driven: the
`skills/literature-evidence.md` skill routes through the
`nature-academic-search` workflow when MCP literature tools are available, and
otherwise consumes OpenAlex-only search results or user-provided verified
citation files (`.nbib`, `.ris`, `.bib`).
