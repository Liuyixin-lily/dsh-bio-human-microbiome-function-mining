---
name: functional-dark-matter-discover
description: >-
  Given a target enzyme sequence, EC number, or substrate-product reaction,
  discover candidate human microbiome protein functions by combining sequence
  screening, structure screening, DEER fallback, FedKEA validation, existing
  source annotations, and experimental design.
language: mixed
category: main
---

# Functional Dark Matter Discovery

Use this skill when the user supplies a target enzyme (sequence, EC number, or
substrate + product) and wants candidate human microbiome proteins that may
perform the same reaction, especially proteins missed by conventional
annotation.

**Tool boundary**: heavy external tools (DIAMOND, CD-HIT, US-align, DEER,
FedKEA, Bakta) are not bundled. The Agent runs them only when the user gives
executable and data paths that are accessible from the current terminal and
allows direct execution. Otherwise the Agent gives exact commands and consumes
the returned output files. Never call FedKEA web programmatically. See
`references/tool_fallback.md` and `references/acceptance_criteria.md`.

## Inputs

Normalize the input into a target function card before searching. Include when
available:

- target enzyme name
- EC number
- reaction, substrate, product, cofactor
- known catalytic residues
- structural fold
- known human/microbial reference enzymes
- related metabolic pathway

## Workflow

0. **Check what the user already supplied BEFORE any acquisition step.** This
   rule overrides every later step that would download or predict something.
   Inventory, for this task:
   - candidate proteome `.faa` and/or annotated `.gbff`
   - **target sequence** (`inputs.target_sequence_fasta`)
   - **target structure** (`inputs.target_structure_pdb`), plus any catalytic
     residue / pocket table
   - **candidate structure directory** (existing PDB/CIF models per candidate)

   For each item: if the user supplied a readable, non-empty file (or a
   directory that already contains the candidate structures), that item is
   **PROVIDED** - use it directly and do **NOT** download, re-fetch, re-annotate
   or predict it. Only items that are absent or empty are **TO ACQUIRE**.
   State that split explicitly and record it in `project.json`, then verify the
   PROVIDED paths with `scripts/preflight_inputs.py --project project.json`
   (add `--require-target-sequence` / `--require-target-structure` /
   `--require-genome-complete` for the route in use). Never re-download or
   re-predict a path the user already handed over, and never overwrite a
   user-supplied file.

   If the user already has a candidate proteome `.faa` and/or annotated
   `.gbff`, skip dataset preparation. If the user instead has taxa, a source
   such as `gut` or `skin`, or `GCF`/`GCA` accessions, run the bundled
   `genome-search`, `genome-download`, and `genome-annotation` sub-skills first
   according to `references/genome_dataset_preparation.md` and the
   `genome_dataset` config. Run those scripts directly when accessible from the
   current terminal; otherwise give the user the exact commands and wait for
   returned files.
   Before heavy screening, run `scripts/preflight_inputs.py --project
   project.json`. Verify `inputs.candidate_proteome_fasta` and every configured
   candidate-genome `.faa`, `.ffn`, `.gbff`, and structure directory. Add
   `--require-genome-complete` for a complete protein/CDS/GenBank route, or
   `--require-target-sequence` / `--require-target-structure` when the chosen
   target route needs them. Never start sequence/structure screening when
   required paths are missing or empty.
1. Build or load a reference enzyme set from UniProt, BRENDA, KEGG, PDB,
   AlphaFold DB, Pfam, and experimentally validated microbial homologs.
   **Load it when the user already supplied the target sequence/structure, an
   existing `reference_enzyme_set.tsv`, or a reference FASTA.** A supplied
   target sequence or structure already serves as the primary reference - do not
   re-fetch it. Run the fetcher below only for records that are still
   TO ACQUIRE. Use
   `scripts/fetch_reference_enzymes.py` to fetch the reference set
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
   If the current environment has no network access to these public endpoints,
   give the user the exact command to run on a machine with internet access and
   wait for the returned files.
2. Run sequence screening against the user's human microbiome protein database.
   Use DIAMOND for the sequence screen. If `diamond` and the target database
   are accessible from this terminal, run the configured command and parse the
   hit table into `sequence_hits.tsv` and `sequence_candidates.tsv`; otherwise
   give the user the exact DIAMOND command and wait for returned files.
   Before `makedb`, deduplicate the candidate proteome with CD-HIT. If each
   organism is represented by a single genome, default to 100% identity; for
   a multi-genome pan-proteome, default to 95% identity. Allow an explicit
   override in `project.json` or the wrapper command.
3. When the user supplies `.faa` or `.gbff` candidate files that already contain
   protein annotations, parse that existing evidence into
   `source_feature_annotations.tsv`. Preserve protein/gene names, product
   descriptions, EC numbers, Pfam/InterPro/TIGRFAM/CAZy/KEGG/COG/GO identifiers,
   and the original source file path.
4. Classify hits as `known`, `ambiguous`, or `unknown`.
5. Apply the sequence+annotation fast path before any structure work:
   - If a DIAMOND sequence hit has a positive `sequence_score` and its existing
     `.faa`/`.gbff` annotation matches the target (for example
     `source_ec_number` equals the target EC, or `source_product`/annotation
     contains the target enzyme name or a direct reaction-product synonym),
     mark it `SEQUENCE_ANNOTATION_CONFIRMED`.
   - Skip structure-prediction, US-align, DEER, and catalytic-pocket mapping for
     those rows. Move directly to FedKEA validation, literature evidence,
     SignalP extraction, hypothesis generation, and experimental design when
     requested.
   - If DIAMOND finds no sequence hit for a candidate gene or genome, do not
     stop the workflow. Continue to structure screening so that US-align and
     FedKEA can still provide structural and functional evidence.
   - Run structure workflows for candidates where sequence evidence alone is
     absent, ambiguous, unknown, or the existing annotation does not match the
     target function. Existing `.faa`/`.gbff` annotations such as a clear `sph`
     label are still useful as additional evidence in these cases, but an
     annotation alone is not the same as a DIAMOND sequence hit and does not by
     itself mark a row `SEQUENCE_ANNOTATION_CONFIRMED`.
6. Check whether candidate structure files (PDB or CIF) exist for the
   sequence-filtered candidates. Do not assume structures are present.
7. Run the `structure-prediction` sub-skill **only for candidates that are TO
   ACQUIRE**. If the user already supplied candidate structure files (or a
   structure directory that covers them), that is PROVIDED evidence: use those
   files directly as `structure/<protein_sequence_id>.pdb`, skip retrieval and
   prediction, and never overwrite them. When a target structure was supplied,
   use it as the US-align reference as-is. Priority for final structures:
   experimental PDB > AlphaFold DB model passing `mean pLDDT >= 60` >
   homology model > de novo prediction. Only continue to US-align after the
   candidate structures are materialized as `structure/<protein_sequence_id>.pdb`.
8. Run US-align directly against the reference target structure for every
   candidate structure file supplied by the user. If the executable and
   structure files are accessible from this terminal, run the configured batch
   command; otherwise instruct the user with the exact batch command and
   consume its `-outfmt 2` output.
9. If a source genome has no US-align candidate above the configured
   structural threshold, treat DEER as a fallback for that genome only. Run it
   locally only when the executable, model checkpoint, and candidate/template
   structure paths are accessible from this terminal and the user agrees;
   otherwise give the user the exact command and wait for the returned DEER
   output.
10. Keep `structural_candidates.tsv` as the full structure-supported candidate
   list, not only rescued proteins.
11. Map reference catalytic residues and compare active pockets for
    structure-screened candidates only.
12. Collect genome-context and ecological evidence when the user supplies those
    datasets.
13. When the user supplies FedKEA output, merge Enzyme Identification and EC
    Number Prediction results into `combined_candidates.tsv` using the
    `fedkea_*` fields. If an accessible local FedKEA executable is configured,
    run it and parse the result files; otherwise instruct the user that they
    can either download and install FEDKEA on their own server
    (<https://github.com/Stevenleizheng/FEDKEA>), or submit the candidate
    sequences to the FedKEA web server
    (<https://www.viromelab.com/software/fedkea>) manually, then return the
    saved result files. For fewer than 20 sequences recommend the FedKEA web
    submission route first; for 20 or more recommend local FEDKEA. Never call
    the FedKEA web server programmatically.
   - Map `binary_result.txt` to `fedkea_is_enzyme` and
     `fedkea_enzyme_probability`.
   - Map `enzyme_result_with_confidence.csv` to `fedkea_final_result`,
     `fedkea_ec_confidence_file`, `fedkea_accepted_name`, and
     `fedkea_other_names`.
   - Keep the original FedKEA file paths and tool version in
     `fedkea_tool_version`.
14. Run the `literature-evidence` sub-skill to search and audit published
    evidence for the target enzyme and for each candidate protein or candidate
    organism. Run `bash scripts/run_literature_search.sh --check` first to
    confirm the route, then search with `--resolve` so hits come back as
    verified PMIDs WITH ABSTRACTS. Use `nature-academic-search` when its MCP
    literature tools are available and the user allows; otherwise the bridge
    falls back to OpenAlex discovery plus PubMed resolution, or accept
    user-provided citations. Search by at least three shapes: enzyme name +
    species, species + expected product/pathway/phenotype, and gene name +
    species - gene symbols and biological-outcome terms often carry the
    literature when the enzyme name does not. **Read every abstract before
    classifying a hit**; never write a `no_evidence` row from titles alone, and
    record the queries used in `source_search`. Write verified literature rows
    to `literature_evidence.tsv`, add `literature_*` fields to candidate rows,
    and cite only verified PMID/DOI sources in the experimental plan.
15. Build sequence, structural, existing source-annotation, and literature
    evidence tables and combine them into `combined_candidates.tsv`. Then run
    `scripts/score_candidates.py` to apply the explicit priority policy above.
    Sequence+annotation matches that already confirm the target function are
    the fast path; structure evidence is only required when sequence and
    annotation do not together confirm the target function.
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
      verified literature plus the user's assay/system constraints, not
      invented.

## Ranking policy

The default final-ranking policy is the explicit priority rules in
`scripts/score_candidates.py`. Priority order:

1. `SEQUENCE_ANNOTATION_CONFIRMED`: DIAMOND sequence hit and existing
   `.faa`/`.gbff` annotation both match the target function, so structure
   screening is skipped.
2. `USALIGN_TARGET_EC`: US-align above threshold and FedKEA assigns target EC.
3. `DEER_FEDKEA_CONFIRMED`: DEER used as fallback and FedKEA confirms enzyme.
4. `USALIGN_OTHER_EC`: US-align above threshold, FedKEA assigns different EC.
5. `USALIGN_NOT_ENZYME`: US-align above threshold, FedKEA predicts not enzyme.
6. `USALIGN_UNVALIDATED`: US-align above threshold, no FedKEA result yet.
7. `DEER_FALLBACK`: DEER used, FedKEA has not confirmed enzyme function.
8. `SEQUENCE_ONLY`: sequence evidence only.
9. `ANNOTATION_ONLY`: only existing source annotations available.

Within the same rule, ties break by structure score descending, then sequence
score descending, then annotation strength descending, then `candidate_id`
ascending.

## Outputs

Return machine-readable evidence whenever possible:

- `target_function_card.json`
- `reference_enzyme_set.tsv`
- `sequence_hits.tsv`
- `source_feature_annotations.tsv`
- `structural_hits.tsv`
- `sequence_candidates.tsv`
- `structural_candidates.tsv`
- `combined_candidates.tsv`
- `literature_evidence.tsv`
- `experimental_hypotheses.tsv`
- `experimental_design.md`

## Guardrails

- Do not claim function from structure alone.
- Preserve provenance for every candidate: database id, genome accession,
  protein id, tool version.
- Do not fabricate PDB, UniProt, PubMed, EC, or KEGG identifiers.
- Do not fabricate PMID/DOI entries or cite literature you did not verify.
- FedKEA EC predictions are supplementary, orthogonal validation; do not treat
  them as biochemical proof.
- Existing `.faa`/`.gbff` annotations are surrogate existing-knowledge evidence;
  do not treat a product name or EC annotation alone as biochemical proof.
- Treat structure-only hits as hypotheses until biochemical activity is
  measured.
- If a tool/database is not available, say what external tool is needed instead
  of inventing results.
