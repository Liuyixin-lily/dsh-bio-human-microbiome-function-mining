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
- `parse_fedkea.py`: parses user-supplied FedKEA output files into
  `fedkea_results.tsv`. Pass `--expected-accessions` (plain accession list, or
  TSV/CSV with an ID column such as `subject_refseq`,
  `candidate_id`/`query_id`/`protein_id`/`id`/`accession`) so the parser can
  verify that FedKEA output accessions can be joined back to the candidate
  subset that was actually submitted. Zero overlap aborts with an error;
  partial mismatch is recorded in `fedkea_notes`.
- `parse_deer.py`: parses DEER `similarity.csv` into a plugin-compatible
  structural evidence table, keeping the raw DEER distance/rank in dedicated
  fields rather than treating that metric as a TM-score. Pass
  `--candidate-dir` plus `--source-genomes` when the candidate structure
  directory contains per-genome symlinks so each DEER hit is mapped to its
  actual source genome.
- `parse_source_annotations.py`: parses existing `.faa` header annotations and `.gbff` CDS annotations into `source_feature_annotations.tsv`.
- `parse_signalp.py`: parses SignalP GFF3 output (and optionally a SignalP
  summary table) into `candidate_signal_peptides.tsv` with one normalized row
  per candidate, including signal peptide/mature boundaries and cleavage site.
  SignalP 6 `CS pos: <X>-<Y>` is used as the cleavage-site source of truth:
  the first X amino acids are removed and the mature protein starts at amino
  acid position Y (1-based).
- `merge_candidates.py`: merges sequence, structure, FedKEA, and existing
  source annotations into `combined_candidates.tsv`. Pass `--project
  project.json` when the project JSON records `candidate_sequences.candidates`
  source genome paths; missing `organism_or_strain` and `assembly_accession`
  values are filled from that metadata instead of remaining blank.
- `score_candidates.py`: assigns deterministic `overall_score`, `overall_rank`,
  `priority_tier`, `priority_rule`, and `priority_order` to the combined table.
  Ranking is TM-score-first by default (`--rank-by structure`); `--rank-by
  priority` selects the tier-first ordering. The priority rules themselves are
  documented in the script and in
  `schemas/combined_candidates.schema.tsv`. Pass `--target-ec` to match the
  configured target EC for FedKEA target EC validation and for the
  sequence+annotation fast path; pass `--target-name` with comma-separated
  enzyme names/synonyms to let existing `.faa`/`.gbff` annotations trigger
  `SEQUENCE_ANNOTATION_CONFIRMED` when paired with a positive DIAMOND hit.
  DEER candidates that FedKEA confirms as enzymes are placed in
  `DEER_FEDKEA_CONFIRMED`, above `USALIGN_OTHER_EC`.
- `summarize_candidates.py`: reads `scored_candidates_full.tsv`, optional
  `candidate_gene_evidence.tsv`, and an optional project JSON, then writes
  `high_confidence_candidate_summary.tsv` (all scored rows with validation
  verdicts), `final_target_candidates.tsv` (the rows matching
  `--final-rules`, default `USALIGN_TARGET_EC,SEQUENCE_ANNOTATION_CONFIRMED`), and
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

Input preflight:

- `preflight_inputs.py`: checks configured
  `inputs.candidate_proteome_fasta`, per-genome `.faa`, `.ffn`, `.gbff`, and
  candidate structure directories before heavy screening. It never creates
  data. Configured candidate paths are validated; `--require-genome-complete`,
  `--require-target-sequence`, or `--require-target-structure` to enforce
  different route requirements.

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
  server programmatically. Pass `--expected-accessions` or set
  `validation_inputs.fedkea.expected_accessions` in `project.json` so the parse
  step checks accession joinability. FedKEA should normally be run on the
  candidate subset produced by sequence/structure screening, not on the entire
  proteome, unless there is an explicit reason to run a whole-proteome scan.
- `run_signalp.py`: runs the configured local SignalP executable when
  accessible and `auto_run_local` is enabled, otherwise writes a pending
  checkpoint with the exact SignalP command and consumes returned output.
  It then parses raw SignalP GFF3 output through `parse_signalp.py` and writes
  `candidate_signal_peptides.tsv`. SignalP is not bundled with the plugin.

Candidate sequence extraction:

- `extract_candidate_sequences.py`: extracts final candidate proteins,
  CDS, gene nucleotide sequences, and optional SignalP-cleaved mature proteins
  from source FASTA files. It reads `--candidates`, `--project`, `--outdir`,
  optional `--candidate-id-column`, and optional `--signalp-tsv`. By default it
  auto-detects the candidate ID column from `candidate_id`/`query_id`/
  `protein_id`/`id`/`subject_refseq`, so structural candidate tables that use
  `subject_refseq` are supported. The written `candidate_proteins.faa`,
  `candidate_cds.ffn`, and `candidate_gene_sequences.fna` use clean
  accession-only FASTA headers (`>WP_...`) so tools such as FedKEA that parse
  the first header token do not emit truncated or `MULTISPECIES:` accessions.
  When genomic `.fna` is available and the CDS
  header carries an NCBI-style `[location=...]`, it writes the true genomic
  locus as `candidate_gene_sequences.fna`; otherwise it falls back to the CDS
  sequence from `.ffn`. If SignalP predicts a secreted protein using the
  `CS pos: <X>-<Y>` convention (mature start = amino acid position Y), it also
  writes the signal-peptide-removed sequence as `candidate_mature_proteins.faa`.
  The TSV `candidate_gene_evidence.tsv` records locus, gene, SignalP, and source
  provenance columns.

Skill-local launchers:

- `skills/screen-sequence-candidates/scripts/run_diamond_screening.sh`
- `skills/screen-structure-candidates/scripts/run_usalign_screening.sh`

The plugin does not ship a generic Runner. It can run configured external tools
directly when their executables and inputs are accessible from the current
terminal and `auto_run_local` is enabled. Otherwise the user supplies their own
dataset and runs external tools on their own compute; these scripts parse and
merge the evidence tables the user produces.

Literature evidence is not a bundled search engine, but it now has an
executable bridge rather than a prose-only reference:

- `scripts/run_literature_search.sh` locates the external
  `nature-academic-search` skill and a Python >= 3.10 interpreter, then runs its
  OpenAlex search. `--resolve` pipes the hits through
  `scripts/resolve_literature_hits.py`, which converts DOIs to verified PMIDs
  and fetches abstracts from PubMed XML.
- `--check` reports which skill directory and interpreter were resolved, so the
  route can be verified before it is relied on.

```bash
bash scripts/run_literature_search.sh --check
bash scripts/run_literature_search.sh "sphingomyelinase Staphylococcus epidermidis" --limit 10 --resolve
```

The `skills/literature-evidence.md` skill routes through the
`nature-academic-search` workflow when MCP literature tools are available, and
otherwise consumes this OpenAlex route or user-provided verified citation files
(`.nbib`, `.ris`, `.bib`). A `no_evidence` verdict must be based on abstracts
(not titles) and must record the queries used.
