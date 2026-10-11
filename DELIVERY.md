# Delivery contents

This guide describes what the plugin ships and how a new user should adapt it
to their own dataset and compute environment.

## 0. This is a DeepSeek harness plugin

This package is meant to be installed or loaded into a DeepSeek harness / compatible
agent harness environment. New users do not just read the files: they need to
install the package through `dsh plugin`, or connect the plugin contents
(`agents/deepseek.md`, `skills/`, `scripts/`, `schemas/`, `references/`, `projects/`)
to their harness so the agent can use them.

Start with `QUICKSTART.md` in the plugin root. It explains installation, the built-in
self-check, and how to adapt the plugin to a new dataset.

The plugin is not a hosted service and it does not bundle DIAMOND, US-align, DEER,
FedKEA, or Bakta. Users provide their own datasets, compute, and external tools (or
tool paths already installed on their server).

## 1. Plugin core

- `package.json`: dsh npm package manifest with `dsh.bundle.patch` pointing to
  `cordis.patch.yml`; it is the primary delivery form for DeepSeek Harness.
- `index.js` and `src/`: ESM entry that registers skills and a system-prompt
  section when loaded by dsh.
- `cordis.patch.yml`: dsh bundle patch inserting the plugin row and declaring
  the `human-microbiome-function-mining` agent preset.
- `preset/human-microbiome-function-mining/`: preset persona and preset skills
  installed by `scripts/install-preset.js` into
  `~/.dsh/.agent-presets/human-microbiome-function-mining`.
- `agents/deepseek.md`: DeepSeek agent prompt and execution guardrails.
- `config.minimal.example.json`: lean example configuration for a first run.
- `config.example.json`: fuller project/tool configuration reference.
- `LICENSE`: MIT license for the package.
- `SKILL-PROVENANCE.yaml`: internal skill adaptation ledger.
- `skills/`: main discovery skill plus independent sub-skills.
- `scripts/`: parsing, merging, ranking, and wrapper scripts.
- `schemas/`: machine-readable evidence-table contracts.
- `references/`: thresholds, tool-fallback, evidence, and acceptance rules.

## 2. Sub-skills shipped separately

The following skills are independent deliverables and can be installed or
updated separately:

- `build-target-function-card`
- `screen-sequence-candidates`
- `screen-structure-candidates`
- `literature-evidence`
- `genome-search`
- `genome-download`
- `genome-annotation`

Each skill contains its own `SKILL.md`, scripts, and references where needed.

## 3. Scripts

Use these directly or through the agent skills:

- `fetch_reference_enzymes.py`: autobuilds the reference enzyme set from NCBI
  and RCSB PDB when network access is available.
- `run_diamond.py`: runs CD-HIT deduplication (single-genome 100%; multi-genome
  95%) then DIAMOND screening.
- `run_usalign.py`: runs US-align screening over candidate structures.
- `run_deer.py`: runs DEER as a user-approved fallback only when US-align does
  not leave enough suitable candidates.
- `run_fedkea.py`: runs local FedKEA when configured; it never calls the web
  server programmatically.
- `run_signalp.py`: runs or wraps a user-provided local SignalP executable and
  parses GFF3 output through `parse_signalp.py`.
- `run_bakta.py`: runs Bakta annotation when a genome is newly downloaded and
  annotated by the plugin.
- parsers for the raw outputs above: `parse_sequence_hits.py`,
  `parse_usalign.py`, `parse_deer.py`, `parse_fedkea.py`,
  `parse_source_annotations.py`, `parse_signalp.py`.
- `merge_candidates.py`: merges sequence, structure, FedKEA, and source
  annotation evidence into `combined_candidates.tsv`. Pass `--project` when
  the project JSON records candidate sequence source paths.
- `score_candidates.py`: produces `scored_candidates_full.tsv` with explicit
  `priority_rule` / `priority_order`. A DIAMOND hit whose existing `.faa`/
  `.gbff` annotation matches the target EC or enzyme name/product synonym is
  assigned `SEQUENCE_ANNOTATION_CONFIRMED` and skips structure screening.
- `summarize_candidates.py`: produces `high_confidence_candidate_summary.tsv`,
  `final_target_candidates.tsv`, and `experimental_hypotheses.tsv` from a
  scored table. Pass `--literature literature_evidence.tsv` when verified
  citations are available so hypotheses include literature-backed citations.
- `extract_candidate_sequences.py`: extracts final candidate proteins, CDS,
  gene nucleotide sequences, and optional SignalP-cleaved mature proteins from
  source FASTA files.
- `validate_schema.py`: checks output TSVs against `schemas/`.
- `example_test.py`: end-to-end example test against synthetic inputs. It
  verifies that the parsing, merge, and scoring scripts work together without
  real DIAMOND, US-align, DEER, or FedKEA runs.

## 4. Adapting to a new user dataset

1. Install/load the plugin into the user's DeepSeek harness / agent environment.
2. Copy the plugin tree to the user's compute server only when that server is the
   place where the agent runs commands, or when the user wants to run the scripts
   directly from that server.
3. Copy `config.minimal.example.json` first. Copy `config.example.json` or the
   example project JSON under `projects/` when you need DEER/FedKEA/Bakta or
   genome-prep fields. Edit the input and tool paths in `project.json`:
   - target enzyme FASTA
   - target structure PDB
   - candidate proteome `.faa` or annotated `.gbff`
   - per-genome `.fna` genomic FASTA when the user wants the candidate gene's
     nucleotide sequence output (or obtain it through `genome-download`)
   - DIAMOND/CD-HIT, US-align, optional DEER, optional FedKEA/Bakta/SignalP
     paths
   - candidate PDB/CIF structure directory or individual structure files
4. Run `example_test.py` first to verify that the parser/merge/score logic works
   without external tools.
5. Ask the agent to run the target-specific workflow from `README.md` or
   `references/workflow.md`. Structure screening is only run when sequence hits
   and existing annotations do not together confirm the target function.
6. If external tools are not accessible from the terminal, the plugin writes
   pending checkpoints with exact commands for the user to run. The user
   returns the resulting files and the same parsers merge and score them.
7. Generate the final compact deliverables with `summarize_candidates.py`.

The plugin is a DeepSeek harness delivery package around analysis logic, not a
hosted service. Users must install/load the plugin into their harness. External
tools and compute remain on the user's own environment; the Agent can run those
tools only when their paths are accessible from the current terminal and the
user explicitly allows direct execution.

## 5. External tool install links

The Agent does not download or install DEER/FedKEA silently. If a user wants to
run these themselves, point them to the upstream repositories:

- DEER structure retrieval: <https://github.com/WangJiuming/deer>
- FedKEA enzyme/EC prediction (local): <https://github.com/Stevenleizheng/FEDKEA>
- FedKEA web server (manual submission): <https://www.viromelab.com/software/fedkea>

For candidate lists shorter than 20 sequences, the FedKEA web server is usually
the fastest validation route. For larger batches, recommend installing FedKEA
locally and giving `validation_inputs.fedkea.script_path` the path to its
`main.py`.

When running FedKEA locally inside a conda environment, the wrapper expects
`python` to be the FedKEA environment's interpreter because `main.py` launches
helper subprocesses with `python`. On systems where `numpy`/`torch` fail with
missing `CXXABI_1.3.9` symbols, set both `PATH` and `LD_LIBRARY_PATH` in the
active conda environment before running, or encode them in
`validation_inputs.fedkea.env` in `project.json`. See
`references/tool_fallback.md` for the exact command tested on the provided
demo server.
