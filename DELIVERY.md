# Delivery contents

What this package ships, and how to adapt it to a new dataset. For installation and a first run, read
`QUICKSTART.md` first.

## What this package is

A DeepSeek Harness plugin: install it with `dsh plugin` (or load the tree into a compatible harness)
so the agent can use the skills in `skills/`. It is **not** a hosted service and it does not bundle
DIAMOND, CD-HIT, US-align, DEER, FedKEA, Bakta or SignalP — you supply the data, the compute and the
tool paths.

## What is inside

| Path | Contents |
| --- | --- |
| `package.json`, `index.js`, `src/`, `cordis.patch.yml` | npm/bundle entry that registers the skills and the system-prompt section |
| `preset/human-microbiome-function-mining/` | agent preset (persona + orientation skill), installed by `scripts/install-preset.js` into `~/.dsh/.agent-presets/` |
| `agents/deepseek.md` | agent prompt and execution guardrails |
| `skills/` | 12 skill documents (`skills/<name>.md`) plus the asset directories they call (`scripts/`, `references/`) |
| `scripts/` | parsers, wrappers, ranking and self-check scripts |
| `schemas/` | evidence-table contracts (TSV) and the JSON library/card schemas |
| `references/` | workflow, thresholds, decision points, fallback and evidence rules |
| `library/` | selectable targets: `skin` (curated, one evidenced process) and `skin_xenobiotic` (starter, 6 xenobiotic classes) |
| `docs/` | workflow diagram (zh / en) and the script that regenerates it |
| `projects/`, `demo/`, `examples/` | example project configs, a recorded real-data demo, the quarantined legacy library |
| `resources/taxa/` | skin / oral species lists and the GMPS manifest |
| `config.minimal.example.json`, `config.example.json` | lean and full configuration references |
| `LICENSE`, `SKILL-PROVENANCE.yaml` | MIT license; which upstream skills this plugin absorbs |

The library is deliberately small; coverage is **content, not capability**.
`scripts/resolve_target_intent.py` routes an uncovered question, `scripts/build_library_domain.py`
creates a new starter domain with the honesty rules enforced in code, and
`scripts/attach_library_evidence.py` is the only way an entry can become `literature_verified`.

## Skills

`intake-environment` · `browse-target-library` · `build-target-function-card` ·
`functional-dark-matter-discover` · `screen-sequence-candidates` · `screen-structure-candidates` ·
`structure-prediction` · `literature-evidence` · `genome-search` · `genome-download` ·
`genome-annotation` · `prepare-cro-work-order`

## Scripts, by role

- **Target and menu**: `build_target_function_card.py`, `browse_target_library.py`,
  `resolve_target_intent.py`, `build_library_domain.py`, `attach_library_evidence.py`,
  `record_query.py`.
- **Candidates**: `discover_enzyme_candidates.py`, `build_candidate_shortlist.py`, `run_entry_b.py`,
  `score_target_priorities.py` (the two ranked candidate lists).
- **Screening**: `fetch_reference_enzymes.py` (reviewed templates), `run_diamond.py` (CD-HIT +
  DIAMOND), `run_usalign.py`, `run_deer.py`, `run_fedkea.py`, `run_signalp.py`, `run_bakta.py`.
- **Parsers**: `parse_sequence_hits.py`, `parse_usalign.py`, `parse_deer.py`, `parse_fedkea.py`,
  `parse_signalp.py`, `parse_source_annotations.py`, `merge_source_annotations.py`.
- **Evidence and ranking**: `merge_candidates.py`, `score_candidates.py`, `summarize_candidates.py`,
  `extract_candidate_sequences.py`.
- **Checks**: `preflight_inputs.py`, `validate_schema.py`, `check_deliverables.py`, `decisions.py`
  (judgement gates), `example_test.py` (end-to-end test without external tools).

## Adapting to a new dataset

1. Install the plugin into your harness, and put the tree on the machine where the agent runs commands
   only if the tools live there.
2. Start from `config.minimal.example.json`; move to `config.example.json` or a `projects/` example when
   you need DEER / FedKEA / Bakta / genome-prep fields.
3. Fill in `project.json`: target FASTA / PDB or EC+reaction, candidate proteome `.faa` (and `.gbff`,
   `.fna` for gene sequences), candidate structure directory, tool paths, and the literature source.
4. Run `python3 scripts/example_test.py` once — it needs no external tools and catches a broken install.
5. Hand the target to the agent, or run the documented commands yourself. Deliverables land in
   `outputs/task/`; `python3 scripts/check_deliverables.py --project-dir <dir>` says what is missing.

When a tool is not reachable from the terminal, the wrappers write a pending checkpoint with the exact
command; the same parsers consume the files you return.

## External tools

The agent never downloads or installs these silently:

- DEER: <https://github.com/WangJiuming/deer>
- FedKEA (local): <https://github.com/Stevenleizheng/FEDKEA>
- FedKEA web (manual submission): <https://www.viromelab.com/software/fedkea>

For fewer than ~20 sequences the FedKEA web server is usually fastest; for larger batches install it
locally and point `validation_inputs.fedkea.script_path` at its `main.py`. FedKEA runs on the screened
candidate subset, not the whole proteome — pass `--expected-accessions` so a zero-overlap join fails
loudly instead of silently validating nothing. If `numpy`/`torch` report missing `CXXABI_1.3.9`
symbols, set both `PATH` and `LD_LIBRARY_PATH` for the conda environment (or record them in
`validation_inputs.fedkea.env`). Details: `references/tool_fallback.md`.
