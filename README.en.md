# Human Microbiome Function Mining Plugin

DeepSeek Harness (dsh) plugin for discovering candidate proteins with a target enzyme function from human-associated microbial genomes. Chinese version: [README.md](README.md)

`human-microbiome-function-mining` is a plugin package designed to be installed into DeepSeek Harness or a compatible Agent harness. It organizes target enzyme input standardization, reference enzyme collection, candidate genome preparation, CD-HIT deduplication, DIAMOND sequence screening, US-align structural evidence, DEER fallback, FedKEA enzyme/EC validation, existing annotation evidence, literature evidence audit, falsifiable experimental hypothesis generation, and experimental design into reusable workflows.

Users install or load the package into their harness; the Agent can then use the bundled skills, scripts, schemas, and reference rules. The plugin does not host services, does not bundle external bioinformatics tools, and does not provide compute.

Start with [QUICKSTART.md](QUICKSTART.md) for installation, loading, and adapting the plugin to your own data.

---

## What it is

- Turns a target enzyme sequence, EC number, or substrate-product reaction into candidate microbial proteins.
- Standardizes the target into a `target_function_card.json`.
- Organizes sequence screening, structure screening, functional/EC validation, literature evidence, and final ranking.
- Executes external tools only when the user provides accessible executable and data paths and allows the Agent to run them locally. Otherwise it writes exact commands and consumes returned outputs.

The plugin provides skills, scripts, schemas, and reference rules. It does not replace DIAMOND, CD-HIT, US-align, DEER, FedKEA, Bakta, SignalP, or literature databases.

---

## Directory layout

```text
human_microbiome_function_mining/
├── package.json                 # dsh npm package manifest
├── index.js                     # ESM entry
├── cordis.patch.yml             # dsh bundle patch: plugin row + preset declaration
├── src/                         # dsh runtime registration (skills + system prompt)
├── preset/                      # dsh agent preset (persona + preset skills)
├── agents/deepseek.md           # DeepSeek agent prompt and execution guardrails
├── config.minimal.example.json  # lean example configuration
├── config.example.json          # fuller project/tool configuration reference
├── LICENSE                      # MIT license
├── SKILL-PROVENANCE.yaml        # skill adaptation ledger
├── references/                  # workflow, thresholds, fallback and evidence rules
├── schemas/                     # machine-readable evidence-table contracts
├── scripts/                     # parsers, wrappers, ranking, and example test
├── projects/                    # example project configuration files
└── skills/                      # main skill plus independent sub-skills
```

---

## Skills

- `functional-dark-matter-discover`: main workflow that turns a target enzyme/EC/reaction into candidates and experimental design.
- `build-target-function-card`: standardizes target inputs and generates the Target Function Card.
- `screen-sequence-candidates`: runs or consumes DIAMOND sequence screening; defaults to CD-HIT deduplication first (100% for single-genome datasets, 95% for multi-genome pan-proteomes).
- `structure-prediction`: retrieves or predicts missing candidate structures with priority experimental PDB > AlphaFold DB model passing `mean pLDDT >= 60` > homology model > de novo prediction. The bundled PDB/AFDB/homology helper scripts are under `skills/structure-prediction/scripts/` and produce `structure/<protein_sequence_id>.pdb` for US-align.
- `screen-structure-candidates`: structural evidence screening. First check whether candidate structure files exist; if structures are missing, run the bundled `structure-prediction` sub-skill before US-aligning all available candidate structures. Use DEER as a fallback only for a genome when US-align yields no qualifying candidate at all, or not enough of them, and the user agrees. Activate this route only when sequence screening plus existing annotation do not together confirm the target function.
- `literature-evidence`: literature evidence audit. When MCP literature tools are available, follow a `nature-academic-search` style workflow; otherwise provide search terms or accept user-provided verified citation files. Never fabricate PMID/DOI.
- `genome-search`: select candidate GCF/GCA assemblies from NCBI Assembly/BioSample metadata.
- `genome-download`: batch-download RefSeq/GCF or GenBank/GCA genome files.
- `genome-annotation`: build databases and annotate newly downloaded genomes with Bakta.

The three genome sub-skills are independent deliverables. Load them when users have taxa or accession lists but do not already have a candidate proteome `.faa` or annotated `.gbff` dataset.

---

## Core workflow

```text
target enzyme / EC / substrate-product
  -> target_function_card.json
  -> preflight check .faa/.ffn/.gbff and structure paths
  -> optional genome-search / genome-download / genome-annotation
  -> CD-HIT deduplication (100% for single-genome datasets; 95% for multi-genome pan-proteomes)
  -> DIAMOND sequence screening
  -> parse existing .faa/.gbff annotations
  -> fast path: if sequence hit AND existing annotation match the target,
     mark SEQUENCE_ANNOTATION_CONFIRMED and skip structure steps
  -> otherwise check candidate structure files (PDB/CIF)
  -> if structures missing, run bundled structure-prediction sub-skill
  -> direct US-align against the reference target structure for all available candidate structures
  -> DEER only as fallback for genomes with no US-align candidate or too few of them,
     and when the merged sequence+structure candidate list has no qualifying candidate
  -> optional SignalP cleavage prediction for final candidate proteins
  -> optional catalytic-pocket, genome-context, and ecological evidence
  -> optional FedKEA enzyme/EC evidence
  -> literature-evidence audit (verified PMID/DOI evidence)
  -> merge combined_candidates.tsv
  -> explicit priority candidate ranking
  -> falsifiable experimental hypotheses
  -> experimental design
```

Default ranking is produced deterministically by `scripts/score_candidates.py`. A DIAMOND sequence hit whose existing `.faa`/`.gbff` annotation also matches the target function is assigned `SEQUENCE_ANNOTATION_CONFIRMED` and skips downstream structure screening; structure evidence is used only when sequence+annotation evidence is absent, ambiguous, unknown, or contradicts the target. The script sorts by priority, then by structural score, sequence score, annotation strength, and `candidate_id` as tie-breakers. `priority_rule` and `priority_order` are optional traceability columns; the externally delivered ranking field is `overall_rank`.

The final ranked table is `scored_candidates_full.tsv`, with `overall_rank` as the explicit deliverable ranking field. Optional `priority_rule` / `priority_order` columns may be present for traceability but are not required by the schema.

Priority policy used by `score_candidates.py`:

1. `SEQUENCE_ANNOTATION_CONFIRMED`
2. `USALIGN_TARGET_EC`
3. `DEER_FEDKEA_CONFIRMED`
4. `USALIGN_OTHER_EC`
5. `USALIGN_NOT_ENZYME`
6. `USALIGN_UNVALIDATED`
7. `DEER_FALLBACK`
8. `SEQUENCE_ONLY`
9. `ANNOTATION_ONLY`

---

## Tool execution boundary

The plugin does not silently download or install DIAMOND, CD-HIT, US-align, DEER, FedKEA, or Bakta.

1. Ask the user for the **concrete locations** first: the data file paths **and** the executable paths of every tool the route needs (DIAMOND/CD-HIT/US-align, optionally DEER/FedKEA/Bakta/SignalP, including version and `auto_run_local` intent). Ask explicitly whenever a path is absent, still an example placeholder `/path/to/...`, or lives on a remote host - never guess and never assume. Checklist:
   [`references/input_paths.md`](references/input_paths.md).
2. If the data or tools sit on a **remote host**, ask for `user@host` and the absolute path there, and confirm access before running anything.
3. Check whether the executable and required inputs are accessible from the current terminal: `python3 scripts/preflight_inputs.py --project project.json --require-tools` reports `ok` / `placeholder` / `missing` / `invalid` for every configured data and tool path.
4. If accessible and `auto_run_local` is enabled, run the configured command and record the command and version for provenance.
5. If accessible but the user wants only instructions, or it is not accessible, write the exact pending command and consume returned files.
6. Never invent tool output. Never call the FedKEA web server programmatically.

For structure evidence, first check whether candidate structure files (PDB/CIF)
exist. Skip the structure route entirely when a candidate already has a DIAMOND
sequence hit and its existing `.faa`/`.gbff` annotation matches the target
function. If a candidate lacks a structure, run the bundled `structure-prediction`
sub-skill (experimental PDB > AlphaFold DB model passing `mean pLDDT >= 60` >
homology model > de novo) and continue only after the returned structures are
materialized as `structure/<protein_sequence_id>.pdb`. Then use US-align on all
available candidate structure files. Use DEER only for a genome when US-align
yields no qualifying candidate for that genome, or not enough of them, and the user agrees.

---

## Installation

DeepSeek Harness npm/bundle form:

```bash
# Local directory
npx -y @deepseek-ai/dsh plugin --profile web add ./human_microbiome_function_mining

# Tarball built from this repository
npx -y @deepseek-ai/dsh plugin --profile web add ./human_microbiome_function_mining.tar.gz

# Once published/mirrored
npx -y @deepseek-ai/dsh plugin --profile web add @dsh-bio/human-microbiome-function-mining
npx -y @deepseek-ai/dsh plugin --profile web add github:Liuyixin-lily/dsh-bio-human-microbiome-function-mining
```

The `postinstall` script installs the agent preset into
`~/.dsh/.agent-presets/human-microbiome-function-mining`.

---

## Quick start

```bash
cp human_microbiome_function_mining/config.minimal.example.json project.json
```

Edit `project.json` input and tool paths:

- `inputs.target_sequence_fasta`
- `reference_enzyme.enzyme_name` / `ec` (fetched automatically when network is available)
- `inputs.candidate_proteome_fasta`
- `inputs.target_structure_pdb`
- DIAMOND/CD-HIT executable paths
- candidate PDB/CIF structure directory
- US-align executable
- optional DEER `do_retrieval.py` and its `ckpt_dir`
- optional Bakta database and environment
- optional local FedKEA `main.py`
- optional local SignalP executable under `tools.signalp`

Sanity check without external tools:

```bash
cd human_microbiome_function_mining
python3 scripts/preflight_inputs.py --project project.json
python3 scripts/example_test.py
# example test passed
```

Typical wrapper entry points:

```bash
python3 human_microbiome_function_mining/scripts/fetch_reference_enzymes.py --project project.json
python3 human_microbiome_function_mining/scripts/preflight_inputs.py --project project.json
python3 human_microbiome_function_mining/scripts/run_diamond.py --project project.json
python3 human_microbiome_function_mining/scripts/run_usalign.py --project project.json
python3 human_microbiome_function_mining/scripts/run_deer.py --project project.json
python3 human_microbiome_function_mining/scripts/run_bakta.py --project project.json
python3 human_microbiome_function_mining/scripts/run_fedkea.py --project project.json
python3 human_microbiome_function_mining/scripts/run_signalp.py --project project.json
```

External tool sources:

```text
DEER    https://github.com/WangJiuming/deer
FedKEA  https://github.com/Stevenleizheng/FEDKEA
        https://www.viromelab.com/software/fedkea
SignalP https://services.healthtech.dtu.dk/services/SignalP-6.0/
```

For candidate lists shorter than 20 sequences, the FedKEA web server is usually the fastest validation route. For larger batches, install FedKEA locally and point `validation_inputs.fedkea.script_path` at its `main.py`.

FedKEA should normally be run on the candidate protein FASTA produced by
`extract_candidate_sequences.py`, not on the full proteome, unless the user
explicitly requests a whole-proteome enzyme scan. Candidate FASTA headers must
keep the accession as the first field (for example `>WP_...`), and the wrapper
can verify output accession joinability with `--expected-accessions` (or
`validation_inputs.fedkea.expected_accessions` in `project.json`).

For DEER checkpoints on a server without Hugging Face access, place the model files under the configured `tools.deer.ckpt_dir` and set `tools.deer.skip_hf_checkpoint: true` before running.

---

## Usage examples

The examples are organized by common input type and adapted from real, executable
research scenarios:

| Input type | Trigger | Example |
| --- | --- | --- |
| Known metabolic reaction | Substrate/product is known, but no template sequence or EC. | sphingomyelin -> ceramide + phosphocholine |
| Known enzyme name / EC | Functional annotation is known. | neutral sphingomyelinase / EC 3.1.4.12 |
| Known reference sequence | A FASTA or UniProt accession is available. | DDC / P20711 |

Each example contains a prompt you can send directly and the workflow the Agent
will run with the bundled skills. Replace tool and data paths with your own.

### Example 1: predict whether human microbiome microbes encode a target reaction from a product/substrate reaction

```text
User:
"Known metabolic reaction products are ceramide and phosphocholine.
Predict whether the skin microbe Staphylococcus epidermidis
(GCF_038181645.1) contains related metabolic genes and provide a
verifiable experimental design."

Agent:
- Use `build-target-function-card` to infer the reaction from the reported products: sphingomyelin + H2O -> ceramide + phosphocholine (EC 3.1.4.12), written into `target_function_card.json`
- Inventory the inputs: split candidate proteome/genome, target sequence, target structure and candidate structure directory into PROVIDED vs TO ACQUIRE. PROVIDED items are used as-is - no download, re-annotation, prediction or overwrite; use `genome-search` / `genome-download` / `genome-annotation`
  to prepare candidate proteomes **only for TO ACQUIRE items**, and likewise load the reference enzyme set directly when the user already supplied the target sequence/structure
- Verify and pin that split with `preflight_inputs.py`; fail before heavy work when a required path is missing or empty
- Use `screen-sequence-candidates` to run CD-HIT deduplication (single-genome 100%) then DIAMOND sequence screening
- Parse existing `.faa`/`.gbff` protein/gene names, ECs and Pfam/InterPro/KEGG annotations with `parse_source_annotations.py`
- Apply the fast path first: a DIAMOND hit with matching annotation for the target marks the row `SEQUENCE_ANNOTATION_CONFIRMED`
- Attach a verifiable PMID/DOI evidence chain with `literature-evidence` (verified references only)
- Rank with `score_candidates.py` by the explicit priority rules and output `scored_candidates_full.tsv`, `experimental_hypotheses.tsv` and `experimental_design.md`

The response clearly reports:
- whether candidate genes are detected
- representative candidate accession/locus_tag
- evidence chain and confidence
- actionable experimental verification plan
```

### Example 2: predict whether human microbiome microbes encode related metabolic genes from a known enzyme

```text
User:
"Predict whether the three skin microbiome genomes we provide
(Streptococcus pyogenes, Streptococcus thermophilus,
Staphylococcus xylosus) contain metabolic genes related to
neutral sphingomyelinase and provide a verifiable experimental design."

Agent:
- Use `build-target-function-card` for neutral sphingomyelinase / EC 3.1.4.12
- Prepare the reference enzyme set automatically or manually, and record NCBI, PDB, and/or UniProt provenance
- Aggressively check each genome and structure repository path; reject empty/missing required input before heavy work
- Run `preflight_inputs.py` before heavy work and verify each genome's `.faa`, `.ffn`, `.gbff`, and candidate structure directory
- Run `screen-sequence-candidates` on each genome: CD-HIT deduplication (100%), then DIAMOND screening
- For each genome, first check whether a DIAMOND hit already matches the neutral sphingomyelinase / EC 3.1.4.12 annotation; only when there is no sequence hit, check all candidate structure files;
- If structure is missing, run `structure-prediction`, then use `screen-structure-candidates` to US-align all available candidate structure files for that genome directly; treat DEER as a per-genome fallback only when US-align yields no qualifying candidate for that genome, or too few of them, and the user agrees
- Validate final candidates with FedKEA and keep the binary/enzyme/probability outputs
- Use `literature-evidence` to attach verifiable PMID/DOI evidence
- Score with `score_candidates.py` and output per-species candidate tables, representative candidates, and experimental design

The response clearly reports:
- whether each species has candidates
- key evidence for positive/negative results
- whether DEER fallback was used and why
- recommended downstream experiments
```

### Example 3: predict whether human microbiome microbes encode similar metabolic genes from a known sequence

```text
User:
"Predict whether the gut microbe Bifidobacterium adolescentis may encode
the key melatonin synthesis enzyme DDC (P20711) and provide a
verifiable experimental design."

Agent:
- Use `build-target-function-card` for DDC / aromatic L-amino acid
  decarboxylase (EC 4.1.1.28), with UniProt reference = P20711
- If the user does not provide FASTA, give the UniProt retrieval command instead
  of fabricating a sequence; when reference-enzyme fetching is configured, also
  use `fetch_reference_enzymes.py` to prepare local reference records
- Run `scripts/preflight_inputs.py --project project.json` before heavy work
  when candidate genome paths and structure directories are configured
- Use `genome-search` / `genome-download` / `genome-annotation` to prepare
  Bifidobacterium adolescentis candidate proteomes
- Run `screen-sequence-candidates`: CD-HIT deduplication (single-genome 100%,
  multi-genome 95%), then DIAMOND screening
- Check whether a DIAMOND hit already has P20711/DDC-related annotation; if
  yes, mark `SEQUENCE_ANNOTATION_CONFIRMED` and skip structure steps
- Only when sequence hits lack matching annotation, check whether candidate
  structures exist; if missing, run `structure-prediction`, then use
  `screen-structure-candidates` to US-align
  all available structure files directly
- Use DEER fallback only when US-align candidates are insufficient and the user
  agrees; do not replace US-align with DEER
- Cross-check with FedKEA, existing annotations, Pfam/InterPro, etc.
- Audit literature with `literature-evidence` to attach PMID/DOI-backed evidence,
  then apply the final explicit priority rules for ranking

The response clearly reports:
- whether DDC-like candidates are detected
- representative candidate accession/locus_tag
- sequence/structure/FedKEA evidence chain
- an experimental path for validating DDC and melatonin synthesis
```

---

### Turning these examples into your own demo

1. Put the user's data paths and tool paths into `project.json`.
2. If the target is not NSMase/DDC, change `inputs.target_sequence_fasta`, `reference_enzyme.enzyme_name`, and `reference_enzyme.ec`, or start from a substrate/product reaction.
3. Ask the Agent to run the light workflow first: CD-HIT + DIAMOND -> existing-annotation
   match (which can take the `SEQUENCE_ANNOTATION_CONFIRMED` fast path) -> US-align / DEER
   only when needed -> FedKEA -> literature evidence / experimental hypotheses -> final
   ranking.
4. Experimental design should be generated with verified literature and the user's assay context; do not fabricate citations when literature support is absent.

---

---

## Key outputs

- `target_function_card.json`
- `sequence_hits.tsv`
- `sequence_candidates.tsv`
- `structural_hits.tsv`
- `structural_candidates.tsv`
- `literature_evidence.tsv`
- `fedkea_results.tsv`
- `combined_candidates.tsv`
- `scored_candidates_full.tsv`
- `high_confidence_candidate_summary.tsv`
- `final_target_candidates.tsv`
- `experimental_hypotheses.tsv`
- `experimental_design.md`
- `candidate_sequences/candidate_proteins.faa`
- `candidate_sequences/candidate_cds.ffn`
- `candidate_sequences/candidate_gene_sequences.fna`
- `candidate_sequences/candidate_mature_proteins.faa` (SignalP-cleaved secreted proteins only)
- `candidate_sequences/candidate_gene_evidence.tsv`

`scored_candidates_full.tsv` is the final ranked candidate table. The compact deliverables `high_confidence_candidate_summary.tsv` and `final_target_candidates.tsv` point back to the full evidence table.

Raw tool output paths, tool names, versions, thresholds, and source annotations must be preserved in provenance fields. Sequence similarity, structural similarity, computational EC prediction, literature references, and existing annotations are evidence chains, not biochemical proof.

---

## Further documentation

- [QUICKSTART.md](QUICKSTART.md): install and first-use guide.
- [DELIVERY.md](DELIVERY.md): delivery contents and adaptation guide.
- [scripts/README.md](scripts/README.md): parser and wrapper details.
- [schemas/README.md](schemas/README.md): evidence-table contracts.
- [references/tool_fallback.md](references/tool_fallback.md): tool-running and fallback policy.
- [references/literature_evidence.md](references/literature_evidence.md): verified literature evidence chain guide.
- [references/acceptance_criteria.md](references/acceptance_criteria.md): task completion checklist.
