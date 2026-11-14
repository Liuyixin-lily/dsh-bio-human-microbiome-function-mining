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

## Before anything runs (after the target is known)

**The order is: settle the target first, then ask only for what that target needs.** A card-only task should not trigger questions about Bakta or DEER; asking for a server and a database before knowing the target makes the user pay for paths that will never be used.

The plugin bundles no heavy tools, so "can this actually run?" has to be asked, not assumed. The costliest failures in a real project were all environmental: a tool invoked by absolute path without its conda env on `PATH` (`foldseek: command not found`), another needing `PYTHONPATH`, a third hanging while trying to fetch a checkpoint from Hugging Face on a machine with no network, Bakta unable to start because `BAKTA_DB_FULL` was unset, and a shared box already running 146 processes from someone else's project.

```bash
# scope the questionnaire to the task: card touches no external software at all
python3 scripts/intake_environment.py --ask --task card
python3 scripts/intake_environment.py --ask --task screening     # DIAMOND + CD-HIT only
python3 scripts/intake_environment.py --ask --task structure     # plus US-align
python3 scripts/intake_environment.py --ask                      # full six groups, when needed
python3 scripts/intake_environment.py --init --output environment.json
python3 scripts/intake_environment.py --probe --config environment.json \
    --output-card environment_card.json --output-report environment_report.md
```

| status | meaning | allowed |
| --- | --- | --- |
| `ready` | executable exists **and** reports a version containing a number | run it, if execution is permitted |
| `unverified` | runs but reports no version, or a declared env path is missing | not usable; ask for confirmation or a smoke test |
| `missing` | declared but not found | hand over the command |
| `not_provided` | user does not have it | hand over the command |

**These files belong to one user and are never shipped.** `environment.json`,
`environment_card.json` and `config.tools.json` describe a single machine; they are
gitignored, and the plugin itself carries only the questionnaire plus an all-`null`
skeleton. When writing an example for the plugin, use `/path/to/...` placeholders and let
this audit back it up (it also runs in the test suite):

```bash
python3 scripts/intake_environment.py --audit-paths .
```

It fails on a real home directory (`/Users/<name>/`, `/home/<name>/`) or a private IP
address, so no demo config can quietly acquire one person's paths again.

The same answers also generate the `tools` / `inputs` fragment that `project.json`
expects, so nothing is typed twice:

```bash
python3 scripts/intake_environment.py --probe --config environment.json \
    --output-card environment_card.json --emit-config outputs/task/config.tools.json
```

Same rule: **a path is written only for a `ready` tool**; everything else is left empty
with `enabled: false`. If DIAMOND is ready but CD-HIT is not, `sequence_screen` stays
disabled because deduplication is mandatory. A tool whose declared env path is missing
keeps its `env` block so the user can fix it, but is not enabled.

Two hard rules: **a path is not a working tool** (no version means `unverified`, because the real problem usually only appears at run time), and **permission is separate from capability** (if `allow_local_execution` is not true, produce commands only, however ready the tools look). `--check-network` probes NCBI / RCSB / Hugging Face before any auto-downloading step.

## Skills

- `intake-environment`: **the first step before any tool runs.** Ask the user where it runs (local / remote host / they run it themselves), machine resources, the absolute path of every external tool plus the environment variables each needs, database paths, data paths and network availability. The answers go into `environment.json` and `--probe` verifies them. Only `ready` tools may be run, and only when `allow_local_execution` is explicitly true.
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
| `library/skin.json` | Skin: 1 process / 1 enzyme target, **with verified PMIDs** — sphingomyelin phosphodiesterase (EC 3.1.4.12), matching examples 1 and 2 | `shipped_example` |
| `examples/unverified/*.json` | The previous 27 uncited curated entries (skin 10 processes / gut 5), **not loaded by default** | reference material |

**The default library is deliberately tiny.** It holds only entries with real literature support that also match a README example, and passes its own `--require-evidence` gate 1/1. The previous 27 entries carried no citations, so they moved to `examples/unverified/` where that gate quarantines all of them — they are no longer presented as a menu.

**The library itself is optional.** Empty `library/` and the plugin still does everything except offering a menu of "which enzymes to look at first": entry A, per-site genome search, sequence/structure/annotation/literature evidence, ranking and the CRO work order are unaffected. The only countable cost is that `--auto-score` derives 8 components instead of 4.

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

1. **Weights and scores are separate, and computable scores are not typed by hand**: the weights are the standard; the component scores are inputs. `--auto-score` derives the six that follow from artifacts already in the pipeline — `biochemical_clarity`, `microbial_plausibility`, `novelty` (from the library entry), `sequence_structure` (from the reference enzyme set), `genome_availability` and `site_presence` (from the genome-search table) — and records the rubric per cell in `score_sources` (`auto:library`, ...). Two more come from a real literature table: run `literature-evidence` first, then pass `--literature outputs/task/literature_evidence.tsv [--disease "<phenotype>"]`. Only `verified=yes` functional records (`direct_functional_evidence` / `related_assay`) count: 1 -> 3, 2 -> 4, >=3 -> 5; reviews alone -> 2. `no_evidence` rows and unverified records do **not** raise the score, and they do **not** turn it into a 0 either — no evidence is not evidence of absence, so those cells stay gaps. The report lists exactly which references were counted, with evidence type and verified flag. `disease_relevance` is co-occurrence, not causality.

That leaves three genuine judgement calls: assay feasibility, metabolic plausibility, strain accessibility. The script refuses to rank while a required cell is neither given nor derivable, naming each missing cell and the flag that would derive it; `--allow-missing-scores` ranks anyway and records the gap as `missing`.
2. **Subjectivity is visible**: every row carries `score_basis = manual_expert_judgement` and the exact `scoring_policy`, so a ranking can be recomputed and challenged.
3. **Threshold reachability is validated**: the upstream example config set `taxa_min_priority_score` to 948 against a theoretical maximum of about 10.6 on the 0-5 scale, which silently selected zero taxa. That is now a hard error with an explanation.
4. **Legacy format still works**: `skin_process` / `skin_evidence_score` / `skin_presence_score` are read as aliases, so registries written for `select-candidate` run unchanged.

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

## Judgment points

Every decision the plugin must not make for the user is modelled as a choice recorded in
`environment.json` under `decisions`, and they are asked **by stage, not all at once**: `start`
asks only for candidate data; `structure` asks about structure files and the acceptable structure
source; DEER is asked when US-align leaves too few candidates; ranking and delivery ask at their own
step. When a script reaches a stage whose decision is unanswered it stops and prints the options
(`DECISION REQUIRED`) instead of applying a default: `run_deer.py` exits 3,
`summarize_candidates.py` when the delivery table would be empty, `run_usalign.py` when the structure
directory is empty. `--probe` reports `needs_decision`, which is never consent. The full
list and why each must be asked are in `references/decision_points.md`.

## Evidence gates

The ranker will happily produce an order from very little evidence. Two gates stop that:

```bash
python3 scripts/score_target_priorities.py --taxa outputs/taxa/oral_taxa_registry.tsv \
    --site oral --auto-score --allow-missing-scores \
    --require-min-criteria 3 --output outputs/task/priorities
```

| flag | meaning |
| --- | --- |
| `--require-min-criteria N` | at least N components carry a value (judgement counts) |
| `--require-min-evidence N` | at least N components are **data-derived** (`auto:*` only, so judgement cannot satisfy it) |

They answer different questions: the first stops "almost blank but ranked", the second stops
"ranked entirely by opinion". A withheld row keeps no `rank`, is never `selected`, and stays in
the table — hiding it would make the output look more complete than the evidence — with the
reason written to `withheld_rows.tsv`. If nothing passes, the script says the evidence is
insufficient to order anything rather than emitting a quietly empty ranking.

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
entry A (user can name it):  enzyme / EC / substrate-product / sequence
entry B (user only knows):   vague interest "sebum" / "skin barrier" / "body odour"
                               -> browse-target-library: domain -> process -> enzyme
  (both entries converge here)
  -> template sequences + structure files (host templates + microbial templates, curated or
     fetched by fetch_reference_enzymes.py; only entries with experimental evidence, so TrEMBL
     "Inferred from homology" records are not admitted; structures come from UniProt's PDB
     cross-references because US-align cannot run on a FASTA alone)
  -> CD-HIT deduplication (100% for a single genome; 95% for a multi-GCF pan-proteome)
  -> DIAMOND sequence screening (identity >= 0.2, query coverage >= 0.7, E <= 1e-5)
  -> parse_source_annotations (existing .faa/.gbff annotation as an independent layer)
  -> fast path: sequence hit AND annotation agree -> SEQUENCE_ANNOTATION_CONFIRMED
       -> skip structure entirely and report
     (only when the annotation disagrees or is absent does the structure branch run)
  -> ask the user whether candidate protein structures exist
       |-- no  -> structure-prediction
       |          (experimental PDB > AlphaFold DB pLDDT >= 60 > homology model > de novo)
       `-- yes -> US-align over all candidates (TM >= 0.5, both directions)
                   -> DEER fallback only when too few pass, and only with user consent
  -> FedKEA (enzyme/EC evidence) / SignalP (signal peptide)
  -> literature-evidence (verified PMID/DOI only)
  -> merge combined_candidates.tsv
  -> score_candidates.py --project project.json (takes EC/enzyme name from the card; without
     it the fast path cannot be evaluated) -> explicit priority ranking (TM-score first)
  -> falsifiable hypotheses + experimental design
```

**Two questions must be asked before any screening** (see `references/data_intake.md`): where the
candidate proteome/genome is, and whether candidate structure files exist. Both are **choices** recorded in `environment.json` under `decisions` and validated by
`--probe`: `candidate_data` is `user_path` / `download_ncbi` / `not_available`, and
`candidate_structures` is `user_path` / `predict` / `skip`. Choosing `user_path` without a path
reports `needs_field`, and not choosing reports `needs_decision` — an unanswered question is never
consent. Code gates back them up —
`preflight_inputs.py --require-candidate-data` / `--require-candidate-structures`, and
`run_usalign.py` prints the question and writes a `blocked` checkpoint when the structure directory
is empty. Downloading a proteome on the user's behalf, or assuming "no structures" and skipping the
structural branch, produces a result that looks fine but is not the one they asked for.

The pipeline starts from a **template sequence file**, not from a single target sequence. To ask
whether a microbe encodes a host-like enzyme you need both sets: the host's own enzymes (does
the microbial protein resemble a human one?) and microbial homologues (is it the same class of
enzyme?). One set alone misses cases — using microbial templates that were five distant NCBI
hits once produced a false "no candidate" for a proteome that does carry the enzyme.

The final ranked table is `scored_candidates_full.tsv`, with `overall_rank` as the explicit deliverable ranking field. Optional `priority_rule` / `priority_order` columns may be present for traceability but are not required by the schema.

Priority policy used by `score_candidates.py`:

1. `SEQUENCE_ANNOTATION_CONFIRMED`
2. `USALIGN_TARGET_EC`
3. `DEER_FEDKEA_CONFIRMED`
4. `USALIGN_OTHER_EC` (**not an exclusion**: structurally similar while FedKEA predicts another EC. A shared fold can carry convergent or moonlighting activity and FedKEA is only a prediction, so keep these candidates and assay the target reaction and the predicted EC reaction side by side)
5. `USALIGN_NOT_ENZYME`
6. `USALIGN_UNVALIDATED`
7. `DEER_FALLBACK`
8. `SEQUENCE_ONLY`
9. `ANNOTATION_ONLY`

---

## Bundled lists

`resources/taxa/` ships two curated per-site microbe lists (230 oral, 257 skin species), each row carrying a taxon, a genome assembly id and a site-abundance label. They are **not a target library** — no process, no enzyme — but they supply what the library cannot: an authoritative taxon list, concrete accessions, and **measured site abundance**.

```bash
python3 scripts/import_taxon_list.py --list resources/taxa/oral_known_microbes.tsv \
    --site oral --output-dir outputs/taxa
```

It writes `oral_taxa_registry.tsv` (abundance to `site_presence_score`: High 5 / Medium 4 / Low 3 / Scarce 2, with `No Data` left empty rather than scored 0), `oral_genome_accessions.txt` (feed it to `build_gcf_list.py`) and a provenance file with the source sha256. The skin list contains 67 MAG/bin ids that are not NCBI accessions; they are reported separately.

One limitation: the lists supply a single scoring criterion, and with only that filled the ranking ties heavily (230 oral species produce 5 distinct totals). The report says so explicitly. See `resources/taxa/README.md`.

## External data sources

`references/gmps.md` documents GMPS (Human Gut Microbial Protein Structure database: ~2.7M AlphaFold2 structures over 968 gut bacterial and 1,255 phage genomes). It is not a target library — it is a **gut-only** candidate pool and structural evidence source:

```bash
python3 scripts/import_gmps.py --species-map bacteria_N.tar.gz_Species.txt --taxa "Akkermansia muciniphila"
python3 scripts/import_gmps.py --hits gmps_export.tsv --map "query=protein_accession,tm1=tm_score_1" --dry-run --output outputs/task/structural_candidates.gmps.tsv
```

Three limits: **gut only** (no skin or oral, so the body-site dimension is still the library's job); the structures are **AlphaFold2 predictions**, not experimental; and a structural hit is not a function. The importer requires an explicit column mapping, refuses to run without a similarity metric, names any column it did not import, and writes provenance (source file + sha256 + mapping + declared version).

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

Four examples, ordered by what the user already has, all adapted from real runs. Each one gives three
things: **a prompt you can send as-is**, **the chain the Agent actually walks**, and **the result of one
real run**, so you can see what the output looks like before you start. Replace tool and data paths
with your own.

| # | What the user has | Entry point | Example |
| --- | --- | --- | --- |
| 1 | A reaction (substrate -> product) | `reaction` | sphingomyelin -> ceramide + phosphocholine |
| 2 | An enzyme name / EC | `ec` | neutral sphingomyelinase / EC 3.1.4.12 |
| 3 | A reference sequence | `sequence` | DDC / P20711 |
| 4 | Only a focus point | entry B | skin xenobiotic metabolism, then screen alcohol dehydrogenase |

### Example 1: from a metabolic reaction

```text
User:
"Known metabolic reaction products are ceramide and phosphocholine. Predict whether
the skin microbe Staphylococcus epidermidis (GCF_038181645.1) contains related
metabolic genes and provide a verifiable experimental design."
```

**The chain**

- `build-target-function-card` infers the reaction from the products: EC 3.1.4.12, written to
  `target_function_card.json`
- `preflight_inputs.py` inventories the inputs: the proteome is PROVIDED, so it is used as-is - no
  download, no re-annotation
- `screen-sequence-candidates`: CD-HIT (single genome 100%), then DIAMOND (identity>=20 / coverage>=0.7
  / E<=1e-5)
- `parse_source_annotations.py` pulls the existing `.gbff` annotations and joins them onto the hits
- a hit whose annotation agrees becomes `SEQUENCE_ANNOTATION_CONFIRMED` and **structure is skipped**;
  `summarize_candidates.py` writes the delivery set

**Result** (*S. epidermidis* GCF_038181645.1, 2,372 proteins)

| Item | Value |
| --- | --- |
| DIAMOND hits | 7, all pointing at **WP_002468583.1** |
| Best alignment | 52.2% identity / 89.2% coverage / E=7.5e-107 |
| The candidate's own annotation | `MULTISPECIES: sphingomyelin phosphodiesterase` (agrees with the target) |
| Templates hit | all 7 come from **bacterial** phospholipase C templates (*Bacillus cereus*, *Leptospira interrogans*, *Listeria ivanovii*); **no host sphingomyelinase template matched** |
| Verdict | `SEQUENCE_ANNOTATION_CONFIRMED`, structure skipped |

**Why it matters**: **the host templates missed and the bacterial ones hit.** Under one EC the host and
bacterial folds differ, so using the host enzyme as the template to find a bacterial gene finds
nothing; finding a bacterial gene needs a microbial template.

### Example 2: from an enzyme / EC, several genomes

```text
User:
"Predict whether the three skin microbiome genomes we provide (Streptococcus pyogenes,
Streptococcus thermophilus, Staphylococcus xylosus) contain metabolic genes related to
neutral sphingomyelinase and provide a verifiable experimental design."
```

**The chain**

- Build the card for EC 3.1.4.12 and fetch reviewed templates (host + microbial)
- CD-HIT (100%) and DIAMOND per genome: **no hits in any of them**
- Switch to the structure channel: US-align every candidate structure file (both-direction TM>=0.5)
- `parse_fedkea.py` plus `merge_candidates.py --fedkea` validate the EC, then score and summarize

**Result**

| Item | Value |
| --- | --- |
| Sequence channel | **0 hits** in all three genomes, even with the coverage filter relaxed |
| Structure channel | US-align over 1,625 / 1,744 / 2,795 structure files -> **2 / 3 / 1** candidates |
| FedKEA promotion | *S. pyogenes* `WP_023610742.1` (TM 0.7088) and *S. thermophilus* `..._bin.19_00773` (TM 0.6988) -> `USALIGN_TARGET_EC` |
| The rest | `USALIGN_OTHER_EC` (TM threshold met, FedKEA assigns a different EC) |
| DEER | not used |

**Why it matters**: the first run of this example **skipped FedKEA**, so the final table was empty. The
empty-table note now opens with "check whether FedKEA was run", not with "widen the rule set".

### Example 3: from a reference sequence

```text
User:
"Predict whether the given gut microbe Bifidobacterium adolescentis may encode the key
enzyme of human melatonin synthesis, DDC (P20711), and provide a verifiable
experimental design."
```

**The chain**

- Build the card from DDC / EC 4.1.1.28 / reference P20711 (with no FASTA supplied, give the retrieval
  command rather than inventing a sequence)
- CD-HIT (100%) then DIAMOND: **0 hits**
- Structure channel: US-align all candidate structures directly
- FedKEA cross-check, then rank by TM and write the hypotheses

**Result**

| Item | Value |
| --- | --- |
| Sequence channel | **0 hits** |
| Structure channel | 18 candidates, TM 0.60-0.71 both directions, best template 3RBF |
| FedKEA | **other ECs** for all of them (4.1.2.48, 2.1.2.1, 2.6.1.x, 4.4.1.13, 2.8.1.7) |
| Verdict | all 18 are `USALIGN_OTHER_EC` |

**Why it matters**: the delivery does **not** say "no candidate". These are structurally similar
proteins whose predicted EC differs, and they come with a side-by-side assay for the target EC and the
predicted one - a shared fold can carry convergent or moonlighting activity, and FedKEA is a
prediction.

### Example 4: focus on a physiological process, get the ranked lists, then hand off to screening

```text
User:
"I am interested in the physiological processes of skin xenobiotic metabolism.
Which metabolic enzymes and which microbes are worth looking at?"
```

**The chain**

- Routes to entry B: a focus point only, no EC, reaction or sequence
- Search the library: `skin_xenobiotic` holds six xenobiotic classes, all `starter` (no per-item
  evidence), and the hits must be labelled as such
- The library does not cover it fully, so `discover_enzyme_candidates.py` fills in from literature (a
  CJK topic is mapped through a fixed domain-term table; if nothing maps, the agent asks)
- `build_candidate_shortlist.py` merges the library, the literature discovery and the site taxa list
  into two recommendation tables (evidence tier first, score within the tier)

**Result: recommended enzymes**

| Rank | Enzyme | EC | Evidence |
| --- | --- | --- | --- |
| 1 | azoreductase (Azo1) | - | `literature_verified` (PMID 33385118) |
| 2 | beta-glucuronidase | 3.2.1.31 | `curated_prior` (PMID 26972811, 36099474; extrapolated from gut) |
| 3-6 | epoxide hydrolase / 4-hydroxybenzoate 1-hydroxylase / naphthalene 1,2-dioxygenase / alcohol dehydrogenase | - | `curated_prior` (references retrieved, not sufficient for a skin claim) |

**Result: recommended microbes**

| Rank | Microbe | Site presence | Metabolic plausibility |
| --- | --- | --- | --- |
| 1 | *Cutibacterium acnes* | 5.000 | 4.000 |
| 2 | *Staphylococcus epidermidis* | 5.000 | 4.000 |
| 3 | *Staphylococcus aureus* | 5.000 | 3.000 |

Pick one row and `run_entry_b.py --select <target_id> --ec <EC> --proteome ...` hands it off to entry A.
The follow-up below is one real handoff:

```text
User (follow-up):
"Mine alcohol dehydrogenase in Staphylococcus epidermidis."
```

- The follow-up names an enzyme **family** and a species, still no EC, reaction or sequence: a family
  name is not a target
- Converge first: `alcohol dehydrogenase` maps to several ECs; the user picks EC 1.1.1.1
- Hand off to entry A: card, reviewed templates, CD-HIT (100%), DIAMOND, join source annotations

**Result after the handoff** (*S. epidermidis* GCF_038181645.1, 2,372 proteins)

| Rank | Candidate | Template | Identity | Coverage | E | Annotation |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | WP_002438761.1 | sp\|P39451\|ADHP_ECOLI | 68.5% | 99.7% | 2.1e-161 | alcohol dehydrogenase **AdhP** |
| 2 | WP_002456130.1 | sp\|P0A9Q7\|ADHE_ECOLI | 49.3% | 95.8% | 8.9e-274 | bifunctional AdhE |
| 3 | WP_002470719.1 | sp\|P9WQB9\|ADHD_MYCTU | 39.9% | 97.8% | 9.9e-76 | zinc-dependent ADH family |
| 4 | WP_002456033.1 | sp\|Q0KDL6\|ADH_CUPNH | 34.9% | 96.2% | 9.5e-62 | zinc-dependent ADH family |

26 reviewed templates, 24 template-candidate alignments, four proteins through the fast path. A
2,3-butanediol dehydrogenase at 25.4% identity is **not** confirmed: its annotation is a different
activity.

**Why it matters**: if the template set contains a same-species entry (*S. epidermidis*'s own reviewed
ADH), the best hit becomes 100% - that is a **self-match**, not cross-species evidence. Check the
template organism before reading 100% as a discovery.

---

### Reproducing them

1. Put your own data and tool paths in `project.json`.
2. If the target is not NSMase / DDC, change `inputs.target_sequence_fasta`,
   `reference_enzyme.enzyme_name`, `reference_enzyme.ec`, or start from substrate/product.
3. Run the light path first: CD-HIT + DIAMOND -> fast path when the annotation agrees -> only then
   US-align / DEER -> FedKEA -> literature evidence and hypotheses -> ranking.
4. Example 4 has two stages: the first needs only the library and literature (no alignment) and yields
   the recommendation tables; the second (ADH) needs a proteome and the alignment tools. **Reproducing
   only the first stage is a legitimate stopping point.**
5. Every example's delivery set lands in `outputs/task/`; verify it with `check_deliverables.py`.

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
