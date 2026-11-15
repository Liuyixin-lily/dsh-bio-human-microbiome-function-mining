# Quickstart: DeepSeek Harness Plugin

Install it, check it, then point it at your own data. What ships and how to adapt it in depth:
`DELIVERY.md`. The workflow itself: `README.md` or `docs/workflow.zh.png`.

## 1. Install

```bash
# from a local directory, a tarball, npm, or GitHub
npx -y @deepseek-ai/dsh plugin --profile web add ./human_microbiome_function_mining
npx -y @deepseek-ai/dsh plugin --profile web add ./human_microbiome_function_mining.tar.gz
npx -y @deepseek-ai/dsh plugin --profile web add @dsh-bio/human-microbiome-function-mining
npx -y @deepseek-ai/dsh plugin --profile web add github:Liuyixin-lily/dsh-bio-human-microbiome-function-mining
```

`postinstall` copies the agent preset into `~/.dsh/.agent-presets/human-microbiome-function-mining`,
so the preset selector shows the `人体微生物功能挖掘专家` persona. For a manual layout the harness must
see `agents/deepseek.md`, `skills/`, `scripts/`, `schemas/`, `references/` and `projects/`. Start a new
session afterwards and confirm `browse-target-library` and `functional-dark-matter-discover` are
available.

## 2. Sanity check

```bash
cd human_microbiome_function_mining
python3 scripts/example_test.py     # ends with "example test passed"
```

No DIAMOND, US-align, DEER or FedKEA needed.

## 3. Answer the environment questionnaire

The plugin bundles no external tools, so it asks what you actually have before planning anything:

```bash
python3 scripts/intake_environment.py --ask                                 # the question groups
python3 scripts/intake_environment.py --init --output environment.json      # record answers
python3 scripts/intake_environment.py --probe --config environment.json \
    --output-card environment_card.json --output-report environment_report.md
```

Each tool lands as `ready`, `unverified`, `missing` or `not provided`. Only `ready` tools are run, and
only when you allowed local execution. A binary that exists but reports no version stays `unverified` —
the usual cause (wrong conda env, missing shared library, no network) only shows up at run time.

## 4. Do you know the target yet?

| You have | Start at | Command |
| --- | --- | --- |
| an enzyme, an EC number, a reaction, or a sequence | **entry A** — go straight to §5, do not detour through the library | `scripts/build_target_function_card.py` |
| only a focus point ("油脂分泌", "体味", "皮肤代谢有哪些过程") | **entry B** — let the library or the literature propose candidates | `scripts/run_entry_b.py` |

Entry B in one command — it searches the library, retrieves literature for every candidate, and writes
the two ranked candidate lists (the retrieval is what fills the evidence components; without it the
scores read ~1.5/5):

```bash
python3 scripts/run_entry_b.py --topic "皮肤外源性物质代谢" --site skin \
    --output-dir outputs/task/entry_b
```

Pick a row, then hand off to entry A with the same command (`--select <target_id> --ec <EC> --proteome
<faa>`). A family name is not a target: one family maps to several ECs, so `--select` without `--ec`
stops and asks.

Browsing the menu directly (the library has `skin` — curated, one evidenced process — and
`skin_xenobiotic` — a 6-class starter domain):

```bash
python3 scripts/browse_target_library.py --list-domains
python3 scripts/browse_target_library.py --list-processes skin_xenobiotic
python3 scripts/browse_target_library.py --search "偶氮染料"
python3 scripts/browse_target_library.py --show skin_azo_dye_reduction
python3 scripts/browse_target_library.py --interactive --output-dir outputs/task
```

The library is a **prior**, not evidence: entries carry `evidence_status: curated_prior` and empty
`evidence_refs` until `literature-evidence` retrieves real identifiers. `--validate` audits the content.

For a topic outside the shipped domains, route it and — if you want it in the menu — build a starter
domain (the builder refuses empty fields and cannot produce a curated or cited domain):

```bash
python3 scripts/resolve_target_intent.py --query "口腔牙周炎相关菌有哪些酶值得看"
python3 scripts/build_library_domain.py --init --domain oral --output specs/oral.json
python3 scripts/build_library_domain.py --build --spec specs/oral.json --output library/oral.json
```

## 5. Use it on your own data

1. Copy the plugin tree somewhere the agent can reach.
2. `cp config.minimal.example.json project.json`.
3. Edit `project.json`: target FASTA / PDB or EC+reaction; candidate proteome `.faa`, optional `.gbff`,
   and per-genome `.fna` if you want gene sequences; candidate structure directory; tool paths
   (DIAMOND, CD-HIT, US-align, optional DEER/FedKEA/Bakta/SignalP); literature source.
4. Let the agent run the workflow, or run it yourself. It starts with
   `python3 scripts/preflight_inputs.py --project project.json`, which verifies every path before any
   heavy step. A DIAMOND hit whose existing `.faa`/`.gbff` annotation agrees with the target becomes
   `SEQUENCE_ANNOTATION_CONFIRMED`, and structure screening is skipped for it.
5. If a tool is not reachable from the terminal, the wrapper prints the exact command; you run it and
   the same parsers consume the result.

## 6. Deliverables

```bash
python3 scripts/merge_candidates.py --structural outputs/usalign/structural_candidates.tsv \
    --project project.json --output outputs/task/combined_candidates.tsv
python3 scripts/score_candidates.py --input outputs/task/combined_candidates.tsv \
    --project project.json --output outputs/task/scored_candidates.tsv
python3 scripts/summarize_candidates.py --scored outputs/task/scored_candidates.tsv \
    --project project.json --literature outputs/task/literature_evidence.tsv --outdir outputs/task
python3 scripts/check_deliverables.py --project-dir .
```

Everything lands in `outputs/task/`:

- `final_target_candidates.tsv` — one row per protein, with the template it matched and the alignment;
- `final_target_candidates_note.md` — required when the table is empty ("empty" is not "none");
- `high_confidence_candidate_summary.tsv`, `experimental_hypotheses.tsv`, `scored_candidates.tsv`;
- extracted sequences under `candidate_sequences/` when you asked for them (proteins, CDS, genes,
  mature proteins when SignalP predicts a signal peptide).

`experimental_design.md` and the optional `cro_work_order.md` + `cro_modules.tsv` + `cro_sequences.faa`
+ `cro_gap_list.md` complete the package:

```bash
python3 scripts/build_cro_work_order.py --card outputs/task/target_function_card.json \
    --candidates outputs/task/final_target_candidates.tsv \
    --sequences outputs/task/candidate_sequences/candidate_proteins.faa \
    --outdir outputs/task/cro_package --scope candidates
```

Prices and turnaround times stay blank on purpose (the vendor quotes them), and sequences are copied
verbatim or not written at all.

## 7. External tools are yours

DIAMOND, CD-HIT, US-align, DEER, FedKEA, Bakta and SignalP are not bundled. Give their paths in
`project.json`; the agent runs them only when they are reachable and you allowed it. Sources and the
FedKEA join/env notes: `DELIVERY.md` §External tools, plus `references/tool_fallback.md`.
