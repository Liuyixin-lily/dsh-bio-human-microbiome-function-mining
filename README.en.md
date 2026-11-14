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
├── library/                     # curated selectable target index (domain -> process -> enzyme)
├── schemas/                     # machine-readable evidence-table contracts
├── scripts/                     # parsers, wrappers, ranking, and example test
├── projects/                    # example project configuration files
└── skills/                      # main skill plus independent sub-skills
```

---

## Two ways in

The plugin has **two peer entries**. Which one you take depends only on what the
user already has; neither is preferred and neither runs first.

| What the user has | Which entry | Key skill |
| --- | --- | --- |
| **A nameable target**: enzyme name, EC number, substrate-product reaction, or a sequence | **Entry A · explicit card** (start here directly, no library step) | `build-target-function-card` |
| **Only an interest**: a physiological process, a phenotype, a body site, or "which microbes are worth looking at?" | **Entry B · pick from the target library** (the library opens up the three levels for the user) | `browse-target-library` |

Both converge at `target_function_card.json`; everything after that is identical.
They also compose: pick with entry B, then review the fields with entry A. **When
the target is already known, do not detour through the library** — it adds a step
and buys nothing.

---

## Skills

- `browse-target-library`: entry B. When the user has not named an enzyme, EC number, or sequence yet and only says what they care about ("what are the important processes in skin metabolism?", "I care about sebum secretion", "which microbes or enzymes are worth looking at?"), use the shipped target library to open up body site -> physiological process -> enzyme target as a numbered choice list, then materialize the selection as `target_function_card.json`. **Not needed when the target is already known.**
- `build-target-function-card`: entry A. Standardizes target inputs and generates the Target Function Card; start here directly when the user can name the enzyme / EC / reaction / sequence.
- `functional-dark-matter-discover`: main workflow that turns a target enzyme/EC/reaction into candidates and experimental design.
- `screen-sequence-candidates`: runs or consumes DIAMOND sequence screening; defaults to CD-HIT deduplication first (100% for single-genome datasets, 95% for multi-genome pan-proteomes).
- `structure-prediction`: retrieves or predicts missing candidate structures with priority experimental PDB > AlphaFold DB model passing `mean pLDDT >= 60` > homology model > de novo prediction. The bundled PDB/AFDB/homology helper scripts are under `skills/structure-prediction/scripts/` and produce `structure/<protein_sequence_id>.pdb` for US-align.
- `screen-structure-candidates`: structural evidence screening. First check whether candidate structure files exist; if structures are missing, run the bundled `structure-prediction` sub-skill before US-aligning all available candidate structures. Use DEER as a fallback only for a genome when US-align yields no qualifying candidate at all, or not enough of them, and the user agrees. Activate this route only when sequence screening plus existing annotation do not together confirm the target function.
- `prepare-cro-work-order`: turns a target plus candidate list into a **contract research work order a company can quote and execute** (M1 gene synthesis ... M10 data/biosafety), with verbatim sequences, pre-registered decision rules, a plain-language glossary and a "confirm before sending" checklist. Prices and turnaround times are left blank for the vendor.
- `literature-evidence`: literature evidence audit. When MCP literature tools are available, follow a `nature-academic-search` style workflow; otherwise provide search terms or accept user-provided verified citation files. Never fabricate PMID/DOI.
- `genome-search`: select candidate GCF/GCA assemblies from NCBI Assembly/BioSample metadata.
- `genome-download`: batch-download RefSeq/GCF or GenBank/GCA genome files.
- `genome-annotation`: build databases and annotate newly downloaded genomes with Bakta.

The three genome sub-skills are independent deliverables. Load them when users have taxa or accession lists but do not already have a candidate proteome `.faa` or annotated `.gbff` dataset.

---

## Target library: let the user pick instead of guess

`library/` is a browsable, searchable, selectable three-level target index (**optional entry B**; when the target is already known, use entry A and skip it):

```text
domain (body site)  ->  process (physiological process)  ->  enzyme (the actual screening target)
```

Users rarely know which enzyme they want; they know a phenotype ("skin metabolism", "oily skin", "body odour"). The library is what catches that phrasing: it lists `process` entries first, then the `enzyme` targets inside a process. Each target carries its EC number plus an EC confidence level, reaction, substrate/product, fold hint, known microbial examples, a recommended workflow **entry point** (`reaction` / `ec` / `sequence`), a `dark_matter` flag, a priority, an honest provenance note, and one experiment that would falsify the proposed function.

| Library file | Content | role |
| --- | --- | --- |
| `library/skin.json` | Skin, `curated`: 10 processes / 19 enzyme targets (sebum lipolysis, ceramide homeostasis, surface acidification, ureolysis, thioalcohol body odour, amino-acid volatiles, nitrate-NO, hyaluronan degradation, Malassezia lipid dependence, lantibiotic competition) | `shipped_example` |
| `library/gut.json` | Gut, `starter`: 5 processes / 8 enzyme targets (bile salt deconjugation, secondary bile acids, TMA, butyrate, tryptophan-indole) | `shipped_example` |

**Those two domains are reference examples, not a coverage claim.** They are skin and gut because the plugin grew out of those two projects, not because of any coverage argument. The per-site capability is generic: target cards, `genome-search` (seven built-in site vocabularies), sequence/structure/annotation/literature evidence are all site-agnostic — only the *menu* of "which enzymes are worth screening at this site" is limited. `--list-domains` prints the same reminder.

```bash
# which body sites are available
python3 scripts/browse_target_library.py --list-domains
# what processes exist for skin
python3 scripts/browse_target_library.py --list-processes skin
# search with the user's own words (Chinese or English)
python3 scripts/browse_target_library.py --search "sebum"
# menu-driven selection, ending in a card
python3 scripts/browse_target_library.py --interactive --output-dir outputs/task
# flatten the whole library into one table for manual ticking
python3 scripts/browse_target_library.py --export-tsv outputs/task/target_library.tsv
# audit the library content itself
python3 scripts/browse_target_library.py --validate
```

A selection writes `target_function_card.json` (`input_source: library` plus `library_id` / `library_version`) and `target_selection.md` (why this process, key taxa, recommended entry point, evidence status, falsifying experiment).

### Ranking several candidates before screening

The library carries a curated `priority` / `attention` hint, which is enough to say what to look at first, but not enough to defend an ordering across a dozen candidates. For that there is a **pre-screening** ranker:

```bash
# build the scoring skeleton from the library (scores stay empty)
python3 scripts/score_target_priorities.py --seed-from-library library/skin.json --output outputs/task/priorities
# fill the 0-5 scores, then rank
python3 scripts/score_target_priorities.py \
  --enzymes outputs/task/priorities/enzyme_registry.seed.tsv \
  --taxa outputs/task/priorities/taxa_registry.seed.tsv \
  --site skin --output outputs/task/priorities
```

It writes `enzyme_priority_ranking.tsv`, `taxa_priority_ranking.tsv`, `selected_taxa.tsv`, `selected_taxa.txt` (feed it straight into `genome_source_search.py taxa --input`) and `ranking_report.md`.

The scoring model was folded in from the local `select-candidate` skill, generalised from skin to any body site, and fixed in three places:

1. **Subjectivity is visible**: every row carries `score_basis = manual_expert_judgement` and the exact `scoring_policy`, so a ranking can be recomputed and challenged.
2. **Threshold reachability is validated**: the upstream example config set `taxa_min_priority_score` to 948 against a theoretical maximum of about 10.6 on the 0-5 scale, which silently selected zero taxa. That is now a hard error with an explanation.
3. **Legacy format still works**: `skin_process` / `skin_evidence_score` / `skin_presence_score` are read as aliases, so registries written for `select-candidate` run unchanged.

A ranking answers "do this first", never "this has the function".

### Beyond the shipped domains

The library holds 2 body sites and 15 processes, but it is **content, not a capability boundary**. When a user asks about periodontitis, the vaginal microbiome, or drug metabolism, the plugin does not go quiet; it escalates in three steps:

| Question shape | Mechanism that answers it | Command |
| --- | --- | --- |
| names an EC / reaction / sequence | entry A, library not involved | `build_target_function_card.py` |
| names a taxon | site-generic: pick NCBI assemblies by source (built-in vocabulary for skin / oral / gut / respiratory / urogenital / blood / environment) | `skills/genome-search/scripts/genome_source_search.py` |
| names only a site or a phenotype the library does not cover | **routing**: classify the question, emit executable steps, and turn the site/phenotype into literature search terms | `scripts/resolve_target_intent.py --query "..."` |
| wants durable coverage of that direction | **on-demand expansion**: spec -> generated starter domain -> automatic validation | `scripts/build_library_domain.py` |

None of these three steps asserts a fact. The router only classifies and composes commands; the builder refuses empty fields, forces `content_status: starter`, forces `evidence_refs` empty, and runs the real library validator before writing.

```bash
# route any question first: it says which path to take and what is missing
python3 scripts/resolve_target_intent.py --query "periodontitis microbiome enzymes" --json

# make oral a selectable site: init spec -> fill -> build (refuses to write invalid content)
python3 scripts/build_library_domain.py --init --domain oral --output specs/oral.json
python3 scripts/build_library_domain.py --build --spec specs/oral.json --output library/oral.json
python3 scripts/browse_target_library.py --validate
```

One deliberate behaviour: **a hit in a different body site does not count as coverage.** Ask about the vaginal microbiome and the skin acidification process is reported as *usable as an analogy only, not as coverage*, then the escalation path runs. It is never presented as the answer.

**The library is a curated prior, not literature evidence.** `evidence_status` defaults to `curated_prior` and `evidence_refs` stays empty; only `literature-evidence` may promote an entry to `literature_verified`, and only after it has actually retrieved PMID/DOI identifiers. `--validate` rejects `literature_verified` with empty or malformed identifiers. Entries marked `dark_matter: true` (body-odour C-S lyase, CutC, baiCD, LanB/LanC) deliberately leave the EC empty rather than borrowing a neighbouring enzyme's number. Adding a body site means adding one `library/<domain>.json`; no code change. Rules: `library/README.md`.

---

## CRO work order

`experimental_design.md` is the minimum experiment list for people who will run the bench work themselves. A user who is not a molecular biologist and simply wants to hand the work to a company (gene synthesis, expression, purification, enzyme assays) needs something else: **a work order that can be quoted and executed**.

```bash
python3 scripts/build_cro_work_order.py \
  --card outputs/task/target_function_card.json \
  --candidates outputs/task/summary/final_target_candidates.tsv \
  --hypotheses outputs/task/summary/experimental_hypotheses.tsv \
  --sequences outputs/task/candidate_sequences/candidate_proteins.faa \
  --outdir outputs/task/cro_package \
  --scope candidates --bsl BSL-1
```

| File | Content |
| --- | --- |
| `cro_work_order.md` | the vendor-facing document: objective, module table, candidate list with sequence status, required controls, **pre-registered decision rules**, "confirm before sending", a one-line-per-term glossary, RFQ questions, boundary statement |
| `cro_modules.tsv` | quotable module table, one row per module |
| `cro_sequences.faa` | sequences copied **verbatim** from the candidate FASTA, provenance in the header |
| `cro_sequences.MISSING.md` | written instead of the FASTA when no sequence exists |
| `cro_gap_list.md` | items to resolve before sending |

Modules (`--scope` selects the set): M1 gene synthesis and cloning · M2 catalytic-residue mutants · M3 small-scale expression and solubility · M4 scale-up and purification · M5 assay development with a positive control · M6 parallel candidate assay · M7 controls and artefact exclusion · M8 extended characterization · M9 cell or strain-level validation · M10 data, biosafety, IP.

Scopes: `assay_first` (no candidates yet — build the assay first) / `candidates` (default) / `full` (adds mutants, characterization, in vivo).

Three hard boundaries, enforced by the script:

1. **No prices or turnaround times.** Every price cell reads `需询价 / quote required`; turnaround is left for the vendor. Inventing a number is worse than leaving it blank, because the user would budget against it.
2. **No invented sequences.** Sequences are copied verbatim from a FASTA the user already has; when there is none, `cro_sequences.MISSING.md` is written instead. A plausible-looking fake sequence sent to a synthesis vendor wastes an entire batch.
3. **Biosafety is a checklist, not a conclusion.** The document prefills a BSL level and lists what the user's institutional biosafety committee must confirm; it never declares a project compliant or exempt.

Decision rules come from `experimental_hypotheses.tsv`, fixed **before** the data arrive: what counts as supported, what counts as refuted, and what counts as inconclusive (insoluble protein or a failed control is an experiment failure, not evidence of no function).

---

## Core workflow

```text
entry A (user can name it):  target enzyme / EC / substrate-product / sequence
entry B (user only knows):   vague interest "oily skin" / "skin barrier" / "body odour"
                               -> browse-target-library: domain -> process -> enzyme
  (both entries converge here)
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

Default ranking is produced deterministically by `scripts/score_candidates.py` and is **TM-score-first** (`--rank-by structure`, the default): rows carrying a TM-score are ordered by it descending, and rows without one - fast-path rows that skipped structure, DEER rows carrying only a distance, sequence-only and annotation-only rows - follow, ordered among themselves by `priority_order`, then sequence score, annotation strength and `candidate_id`. Pass `--rank-by priority` to restore tier-first ordering.

TM-score is the primary key rather than the `priority_rule` tier because for **convergent / moonlighting** targets the validated enzyme typically carries an annotation and FedKEA EC that differ from the target EC, and tier-first ordering demotes it below candidates whose EC merely happens to match. A DIAMOND sequence hit whose existing `.faa`/`.gbff` annotation also matches the target function is assigned `SEQUENCE_ANNOTATION_CONFIRMED` and skips downstream structure screening (so it has no TM-score and lands in the no-TM group, first by priority); structure evidence is used only when sequence+annotation evidence is absent, ambiguous, unknown, or contradicts the target. `priority_rule`, `priority_order` and `rank_policy` are retained for traceability; the externally delivered ranking field is `overall_rank`.

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

DEER's second gate (triggered when nothing in the merged candidate list qualifies)
needs the merged table passed in:

```bash
python3 human_microbiome_function_mining/scripts/run_deer.py \
  --project project.json \
  --combined-candidates outputs/task/combined_candidates.tsv
```

`--template-dir` / `--candidate-dir` / `--outdir` / `--usalign-dir` are read from
`project.json` when omitted, so those two flags are the whole invocation.

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
  to prepare candidate proteomes only for TO ACQUIRE items, and likewise load the reference enzyme set directly when the user already supplied the target sequence/structure
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
- For each genome, first check whether a DIAMOND hit already matches the neutral sphingomyelinase / EC 3.1.4.12 annotation; only when there is no sequence hit, or a hit whose annotation does not match, check all candidate structure files;
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
"Predict whether the given gut microbe Bifidobacterium adolescentis may encode
the key enzyme of human melatonin synthesis, DDC (P20711), and provide a
verifiable experimental design."

Agent:
- Use `build-target-function-card` for DDC / aromatic L-amino acid decarboxylase (EC 4.1.1.28), with UniProt reference = P20711
- If the user does not provide FASTA, give the UniProt retrieval command instead of fabricating a sequence; when reference-enzyme fetching is configured, also use `fetch_reference_enzymes.py` to prepare local reference records
- Run `scripts/preflight_inputs.py --project project.json` to check that the candidate genome files and structure directory exist
- Run `screen-sequence-candidates`: CD-HIT deduplication (single-genome 100%), then DIAMOND screening
- Check whether a DIAMOND hit already has P20711/DDC-related annotation; if yes, mark `SEQUENCE_ANNOTATION_CONFIRMED` and skip structure steps
- Only when there is no sequence hit, or a hit whose annotation does not match, use `screen-structure-candidates` to US-align all candidate structure files directly
- Cross-check with FedKEA, existing annotations, Pfam/InterPro, etc.
- Audit literature with `literature-evidence` to attach PMID/DOI-backed evidence, then rank with `score_candidates.py` (TM-score-first by default; `--rank-by priority` restores priority-tier ordering)

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

### Example 4: start from a target whose enzyme family is very large, and predict whether gut microbes encode the same activity

```text
User:
"Predict whether the given gut microbe Bifidobacterium adolescentis may encode
the key enzyme of human melatonin synthesis, AANAT (Q16613), and provide a
verifiable experimental design."

Agent:
- Use `build-target-function-card` for AANAT / aralkylamine N-acetyltransferase (EC 2.3.1.87), with UniProt reference = Q16613, and record the cofactor (acetyl-CoA) and the fold (GNAT, Pfam PF00583)
- Keep only the target reference in the reference set: human AANAT (reviewed EC 2.3.1.87); no fold controls
- Run `scripts/preflight_inputs.py --project project.json --require-target-sequence --require-target-structure` to check the candidate genome files and the candidate structure directory
- Run `screen-sequence-candidates`: CD-HIT deduplication (single-genome 100%), then DIAMOND; add a second `--sensitive` pass with a permissive E-value for the remote-homolog tail and report the two passes separately
- Because the target is one branch of the GNAT superfamily, run a family census first: `hmmsearch` with Pfam PF00583 to enumerate every GNAT protein in the candidate genome, including a positive control in the same run (human AANAT only). This census, not the DIAMOND hit list, defines the candidate universe
- If the sequence layer has no significant hit (as in this example), use `screen-structure-candidates` to US-align all candidate structures against the target template only; prefer experimental target templates (e.g. 1CJW/1KUV) and follow them when a predicted model disagrees with them
- Cross-check with FedKEA (correct environment, bare-accession FASTA headers); FedKEA returns the most likely single EC (canonical function) and cannot be used to exclude a secondary activity
- Audit literature with `literature-evidence` to attach PMID/DOI-backed evidence, then rank with `score_candidates.py` (TM-score-first by default; `--rank-by priority` restores priority-tier ordering)

The response clearly reports:
- whether a canonical AANAT ortholog exists, and the size of the candidate universe (GNAT family members)
- representative candidate accessions with gene coordinates, plus their sequence / structure / FedKEA evidence chain
- which candidates already have published experimental validation and which are still hypotheses
- an experimental path for validating serotonin/tryptamine acetylation (recombinant expression + LC-MS/MS product confirmation + kinetics benchmarked against known bacterial SNATs + knockout/complementation)
```

> Key difference from Example 3: when the target belongs to a very large superfamily, one extra step is mandatory - **family census (Pfam HMM)** - and the write-up must keep "no canonical ortholog" separate from "no such activity".

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
