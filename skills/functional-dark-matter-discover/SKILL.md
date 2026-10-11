---
name: functional-dark-matter-discover
description: Given a target enzyme sequence, EC number, or substrate-product reaction, discover candidate human microbiome protein functions by combining sequence screening, structure search, catalytic-residue mapping, genome context, ecology evidence, and experimental design.
metadata:
  short-description: Discover candidate microbiome enzymes from a target enzyme/reaction
---

# Functional Dark Matter Discovery

Use this skill when the user supplies a target enzyme (sequence, EC number, or substrate + product) and wants candidate human microbiome proteins that may perform the same reaction, especially proteins missed by conventional annotation.

Tool boundary: Heavy tools (DIAMOND, US-align, DEER, FedKEA) can be run by the
Agent when the user has supplied tool executables and data paths that are
accessible from the current terminal. If paths are not accessible, or a tool
cannot be reached from this environment, give the user the exact command and
wait for the returned output files. See `references/tool_fallback.md` and
`references/acceptance_criteria.md`.

## Inputs

Normalize the input into a target function card before searching. Include when available:

- target enzyme name
- EC number
- reaction, substrate, product, cofactor
- known catalytic residues
- structural fold
- known human/microbial reference enzymes
- related metabolic pathway

## Workflow

0. If the user already has a candidate proteome `.faa` and/or annotated `.gbff`,
   skip dataset preparation. If the user instead has taxa, a source such as
   `gut` or `skin`, or `GCF`/`GCA` accessions, run the bundled
   `genome-search`, `genome-download`, and `genome-annotation` sub-skills first
   according to `references/genome_dataset_preparation.md` and the
   `genome_dataset` config. Run those scripts directly when accessible from the
   current terminal; otherwise give the user the exact commands and wait for
   returned files.
   Before heavy screening, run `scripts/preflight_inputs.py --project
   project.json`. Verify `inputs.candidate_proteome_fasta` and every configured
   candidate-genome `.faa`, `.ffn`, `.fna`, `.gbff`, and structure directory. Add
   `--require-genome-complete` for a complete protein/CDS/GenBank route, or
   `--require-target-sequence` / `--require-target-structure` when the chosen
   target route needs them. Never start sequence/structure screening when
   required paths are missing or empty.
1. Build or load a reference enzyme set from UniProt, BRENDA, KEGG, PDB,
   AlphaFold DB, Pfam, and experimentally validated microbial homologs.
   Use `scripts/fetch_reference_enzymes.py` to fetch the reference set
   automatically from public NCBI and RCSB endpoints. For a target EC number:

   ```bash
   python3 human_microbiome_function_mining/scripts/fetch_reference_enzymes.py \
     --project project.json \
     --enzyme-name "neutral sphingomyelinase" \
     --ec 3.1.4.12 \
     --organism "Homo sapiens" \
     --pdb-ids 5UVG \
     --output outputs/task/reference_enzyme_set.tsv
   ```

   The script writes `reference_enzyme_set.tsv`, `reference_enzymes.faa`, and
   `reference_provenance.json`. It also selects one primary reference enzyme
   and tries to download its local sequence and structure files under
   `<reference_output_dir>/reference_enzymes/`, writing
   `primary_reference.json` with the selected record and local file paths.
   The primary selection rule is: experimental PDB structure records first,
   then UniProt/NCBI annotated records, then the first fetched record.
   Feed the fetched reference FASTA into the upstream sequence screen when the
   user does not already have a reference enzyme set. If the current
   environment has no network access to these public endpoints, give the user
   the exact command to run on a machine with internet access and wait for the
   returned files.
2. Run sequence screening against the user's human microbiome protein database.
   Use DIAMOND for the sequence screen. If `diamond` and the target database
   are accessible from this terminal, run the configured command and parse the
   hit table into `sequence_hits.tsv` and `sequence_candidates.tsv`; otherwise
   give the user the exact DIAMOND command and wait for the returned files.
   Before `makedb`, deduplicate the candidate proteome with CD-HIT. If each
   organism is represented by a single genome, default to 100% identity; for a
   multi-genome pan-proteome, default to 95% identity. Allow an explicit
   override in `project.json` or the wrapper command.
3. When the user supplies `.faa` or `.gbff` candidate files that already contain
   protein annotations, parse that existing evidence into
   `source_feature_annotations.tsv`. Preserve protein/gene names, product
   descriptions, EC numbers, Pfam/InterPro/TIGRFAM/CAZy/KEGG/COG/GO identifiers,
   and the original source file path.
4. Classify hits as `known`, `ambiguous`, or `unknown`.
5. Check whether candidate structure files exist (PDB/CIF) for the
   sequence-filtered candidates. Do not assume structures are present.
6. If candidates lack structure files, run the bundled `structure-prediction`
   sub-skill to retrieve known structures or predict missing structures.
   Priority for final structures:
   experimental PDB > AlphaFold DB model passing `mean pLDDT >= 60` >
   homology model > de novo prediction. Only continue to US-align after the
   candidate structures are materialized as `structure/<protein_sequence_id>.pdb`.
7. Run US-align directly against the reference target structure for every
   candidate structure file supplied by the user. If the executable and
   structure files are accessible from this terminal, run the configured batch
   command; otherwise instruct the user with the exact batch command and
   consume its `-outfmt 2` output.
8. If a source genome has no US-align candidate above the configured
   structural threshold, treat DEER as a fallback for that genome only. Run it
   locally only when the executable, model checkpoint, and candidate/template
   structure paths are accessible from this terminal; otherwise give the user
   the exact command and wait for the returned DEER output.
9. Keep `structural_candidates.tsv` as the full structure-supported candidate list, not only rescued proteins.
10. Map reference catalytic residues and compare active pockets.
11. Collect genome-context and ecological evidence when the user supplies those datasets.
12. When the user supplies FedKEA output, merge Enzyme Identification and EC
    Number Prediction results into `combined_candidates.tsv` using the
    `fedkea_*` fields. If an accessible local FedKEA executable is configured,
    run it and parse the result files; otherwise instruct the user that they
    can either download and install FEDKEA on their own server
    (<https://github.com/Stevenleizheng/FEDKEA>), or submit the candidate
    sequences to the FedKEA web server
    (<https://www.viromelab.com/software/fedkea>) manually, then return the
    saved result files. When the candidate list has fewer than 20 sequences,
    recommend the FedKEA web submission route first because it is usually
    faster than a local install. When there are 20 or more sequences, recommend
    running the FEDKEA software locally on the user's own compute because web
    upload becomes less convenient at scale. Never call the FedKEA web server
    programmatically.
   - Map `binary_result.txt` to `fedkea_is_enzyme` and `fedkea_enzyme_probability`.
   - Map `enzyme_result_with_confidence.csv` to `fedkea_final_result`, `fedkea_ec_confidence_file`, `fedkea_accepted_name`, and `fedkea_other_names`.
   - Keep the original FedKEA file paths and tool version in `fedkea_tool_version` so the validation layer is traceable.
13. When final candidate proteins are selected and the user wants secreted
    protein mature sequences, run SignalP on `candidate_proteins.faa` through
    `scripts/run_signalp.py` (only when the local executable is accessible and
    `tools.signalp.auto_run_local` is enabled) or give the user the exact
    SignalP command and consume returned GFF3 output through
    `scripts/parse_signalp.py`. Then run
    `scripts/extract_candidate_sequences.py` with `--signalp-tsv
    outputs/signalp/candidate_signal_peptides.tsv` and the project JSON to write
    `candidate_proteins.faa`, `candidate_cds.ffn`,
    `candidate_gene_sequences.fna`, `candidate_mature_proteins.faa`, and
    `candidate_gene_evidence.tsv`.
14. Run the `literature-evidence` sub-skill to search and audit published
    evidence for the target enzyme and for each candidate protein or candidate
    organism. Use `nature-academic-search` when its MCP literature tools are
    available and the user allows; otherwise fall back to OpenAlex-limited
    search or user-provided citations. Write verified literature rows to
    `literature_evidence.tsv`, add `literature_*` fields to candidate rows, and
    cite only verified PMID/DOI sources in the experimental plan.
15. Build sequence, structural, existing source-annotation, and literature
    evidence tables and combine them into `combined_candidates.tsv`. Then run
    `scripts/score_candidates.py` to apply the default
    structure-first-then-sequence policy: structure-bearing candidates precede
    sequence-only candidates, and structural score is the primary tie-breaker.
16. Write one functional hypothesis and one experimental validation plan for
    each high-value candidate.
    - Use `scripts/summarize_candidates.py` to write
      `experimental_hypotheses.tsv` after scoring.
    - Each hypothesis row must include target context, an explicit falsifiable
      statement, mechanistic model, testable prediction, critical experiments,
      falsification criteria, ambient/alternative hypothesis, evidence chain,
      and literature citations from verified `literature_evidence.tsv`.
    - The critical experiments include heterologous expression, knockout and
      complementation, specificity controls, and product detection when
      appropriate. Strain-specific transformation, vector, knockout efficiency
      validation, and assay details must be filled in by the Agent from
      verified literature plus the user's assay/system constraints, not invented.

## Outputs

Return machine-readable evidence whenever possible:

- `target_function_card.json`
- `reference_enzyme_set.tsv`
- `sequence_hits.tsv`
- `source_feature_annotations.tsv`
- `structural_hits.tsv`
- `sequence_candidates.tsv`（仅序列证据候选排序）
- `structural_candidates.tsv`（结构证据支持的候选排序）
- `candidate_sequences/candidate_gene_evidence.tsv`
- `candidate_sequences/candidate_gene_sequences.fna`
- `candidate_sequences/candidate_mature_proteins.faa` (optional, SignalP-cleaved)
- `combined_candidates.tsv`（最终合并候选排序）
- `literature_evidence.tsv`
- `experimental_hypotheses.tsv`
- `experimental_design.md`

## Guardrails

- Do not claim function from structure alone.
- Preserve provenance for every candidate: database id, genome accession, protein id, tool version.
- Do not fabricate PDB, UniProt, PubMed, EC, or KEGG identifiers.
- Do not fabricate PMID/DOI entries or cite literature you did not verify.
- FedKEA EC predictions are supplementary, orthogonal validation; do not treat them as biochemical proof.
- Existing `.faa`/`.gbff` annotations are surrogate existing-knowledge evidence;
  do not treat a product name or EC annotation alone as biochemical proof.
- Treat structure-only hits as hypotheses until biochemical activity is measured.
- If a tool/database is not available, say what external tool is needed instead of inventing results.
