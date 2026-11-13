# Quickstart: DeepSeek Harness Plugin

This package is a DeepSeek harness plugin. It must be installed or loaded into
your DeepSeek harness / compatible agent harness before it can be used.

## 1. What you receive

```text
human_microbiome_function_mining/
├── package.json               # dsh npm package manifest
├── index.js                   # ESM entry
├── cordis.patch.yml           # dsh bundle patch: plugin row + preset declaration
├── src/                       # dsh runtime registration (skills + system prompt)
├── agents/deepseek.md            # DeepSeek agent prompt and guardrails
├── skills/                       # workflow skills the agent loads
├── scripts/                      # parsers, wrappers, ranking scripts
├── schemas/                      # evidence-table contracts
├── projects/                     # example project configurations
├── references/                   # workflow, thresholds, fallback rules
├── library/                      # curated selectable target index (domain -> process -> enzyme)
├── LICENSE                       # MIT license
├── SKILL-PROVENANCE.yaml         # skill adaptation ledger
└── QUICKSTART.md                 # this file
```

## 2. Install the plugin

This package is a DeepSeek Harness plugin npm/bundle. Use `dsh plugin` with a
registry reference, GitHub URL, local directory, or tarball:

```bash
# From a local directory
npx -y @deepseek-ai/dsh plugin --profile web add ./human_microbiome_function_mining

# Or from a tarball built from this repository
npx -y @deepseek-ai/dsh plugin --profile web add ./human_microbiome_function_mining.tar.gz

# Or once published/mirrored on npm or GitHub
npx -y @deepseek-ai/dsh plugin --profile web add @dsh-bio/human-microbiome-function-mining
npx -y @deepseek-ai/dsh plugin --profile web add github:Liuyixin-lily/dsh-bio-human-microbiome-function-mining
```

The `postinstall` script copies the agent preset into
`~/.dsh/.agent-presets/human-microbiome-function-mining`, so the preset
selector shows the `人体微生物功能挖掘专家` persona.

For a manual layout, make sure the harness/agent can see:

- `agents/deepseek.md`
- `skills/`
- `scripts/`
- `schemas/`
- `references/`
- `projects/`

After this, start a new agent/assistant session and confirm the plugin skills
`browse-target-library` and `functional-dark-matter-discover` are available.

## 3. First sanity check

From the unpacked plugin tree:

```bash
cd human_microbiome_function_mining
python3 scripts/example_test.py
```

Expected output ends with:

```text
example test passed
```

This does not require DIAMOND, US-align, DEER, or FedKEA to be installed.

## 4. Entry B — only if you cannot name the target yet

This section is **skipped entirely** in the normal case. The only reason to read
it is that you cannot name an enzyme, an EC number, or a sequence, and you only
know *what you care about* — "皮肤代谢有哪些重要的生理过程", "我关注油脂分泌",
"哪些菌值得看", "body odour".

- **You can name the target** (enzyme name / EC / substrate-product / sequence)
  → go straight to section 5 and build the card with `build-target-function-card`.
  Do not detour through the library.
- **You cannot name it yet** → stay here and let the library list the options.

Neither route is the "advanced" one; they just answer different starting points.

```bash
python3 scripts/browse_target_library.py --list-domains             # 皮肤 / 肠道
python3 scripts/browse_target_library.py --list-processes skin      # 皮肤下的生理过程
python3 scripts/browse_target_library.py --search "油脂分泌"         # 用你自己的话搜
python3 scripts/browse_target_library.py --show skin_sebum_lipolysis
python3 scripts/browse_target_library.py --interactive --output-dir outputs/task
```

The last command is a numbered menu: body site -> physiological process -> enzyme
target. Confirming writes `target_function_card.json` and `target_selection.md` into
`outputs/task/`, and tells you which workflow entry point (`reaction` / `ec` /
`sequence`) to use next.

The library is a curated **prior**, not evidence: entries carry `evidence_status:
curated_prior` and an empty `evidence_refs` list, and only `literature-evidence`
may upgrade them after real retrieval. `python3 scripts/browse_target_library.py
--validate` audits the content; `library/README.md` explains how to add a body
site.

Your question will often fall outside the shipped two body sites. That is not a
dead end:

```bash
# route any question: it says which entry to take, and what is missing
python3 scripts/resolve_target_intent.py --query "口腔牙周炎相关菌有哪些酶值得看"

# make a new body site selectable: spec -> starter domain -> validated
python3 scripts/build_library_domain.py --init --domain oral --output specs/oral.json
python3 scripts/build_library_domain.py --build --spec specs/oral.json --output library/oral.json
```

The router asserts nothing; it only classifies the question and composes commands.
The builder refuses empty fields and cannot produce a domain that claims to be
curated or carries citations.

## 5. Use the plugin on your own data

1. Copy the plugin into your DeepSeek harness environment.
2. Create a project configuration:

```bash
cp human_microbiome_function_mining/config.minimal.example.json project.json
```

3. Edit `project.json` with:
   - target enzyme FASTA and target structure PDB, or an EC/reaction
   - candidate proteome FASTA, optional `.gbff`, and, for gene-sequence output,
     per-genome `.fna` genomic FASTA (or download it through the bundled
     `genome-download` skill)
   - candidate structure directory, optional
   - tool paths: DIAMOND, CD-HIT, US-align, optional DEER/FedKEA/Bakta/SignalP
   - literature sources: MCP literature tools when available, otherwise the
     plugin will give you search terms or accept user-provided verified
     citation files

4. Ask the DeepSeek agent to run the workflow. The workflow starts with
   `scripts/preflight_inputs.py --project project.json` and verifies that
   candidate genome `.faa`, `.ffn`, `.fna`, `.gbff`, and structure paths exist
   before running DIAMOND, US-align, DEER, FedKEA, SignalP, or Bakta.
   After DIAMOND sequence screening, if a hit already has matching existing
   `.faa`/`.gbff` annotation for the target EC or enzyme name/product synonym,
   the plugin assigns `SEQUENCE_ANNOTATION_CONFIRMED` and skips downstream
   structure-prediction, US-align, and DEER for that candidate.
5. The agent can execute configured
   tools when they are accessible from the current terminal. If a tool is not
   accessible, the agent prints the exact command for you to run on your own
   compute and then consumes the returned files.

## 6. External tools are yours, the plugin is not a tool installer

This plugin does not bundle DIAMOND, US-align, DEER, FedKEA, or Bakta. You are
expected to provide your own dataset and compute. If you already have those
tools on your server, give the plugin their paths in `project.json`.

External tool sources:

- DEER: <https://github.com/WangJiuming/deer>
- FedKEA local: <https://github.com/Stevenleizheng/FEDKEA>
- FedKEA web (manual submission): <https://www.viromelab.com/software/fedkea>

If you need to hand the bench work to a company instead of doing it yourself,
add `--scope` and a work order in the same run:

```bash
python3 human_microbiome_function_mining/scripts/build_cro_work_order.py \
  --card outputs/task/target_function_card.json \
  --candidates outputs/task/summary/final_target_candidates.tsv \
  --sequences outputs/task/candidate_sequences/candidate_proteins.faa \
  --outdir outputs/task/cro_package --scope candidates
```

It writes `cro_work_order.md` + `cro_modules.tsv` + `cro_sequences.faa` +
`cro_gap_list.md`. Prices and turnaround times are intentionally blank (the vendor
quotes them), and sequences are copied verbatim from your FASTA or not written at
all.

## 7. Final ranked outputs after scoring

```bash
python3 human_microbiome_function_mining/scripts/merge_candidates.py \
  --structural outputs/alignments/run_full_085/structural_candidates.tsv \
  --project project.json \
  --output outputs/task/combined_candidates_full.tsv

python3 human_microbiome_function_mining/scripts/score_candidates.py \
  --input outputs/task/combined_candidates_full.tsv \
  --output outputs/task/scored_candidates_full.tsv \
  --target-ec 3.1.4.12

python3 human_microbiome_function_mining/scripts/summarize_candidates.py \
  --scored outputs/task/scored_candidates_full.tsv \
  --gene-evidence outputs/task/candidate_sequences/candidate_gene_evidence.tsv \
  --literature outputs/task/literature_evidence.tsv \
  --project project.json \
  --outdir outputs/task/summary
```

The final deliverables are:

- `outputs/task/scored_candidates_full.tsv`
- `outputs/task/combined_candidates_full.tsv`
- `outputs/task/candidate_sequences/candidate_proteins.faa`
- `outputs/task/candidate_sequences/candidate_cds.ffn`
- `outputs/task/candidate_sequences/candidate_gene_sequences.fna`
- `outputs/task/candidate_sequences/candidate_mature_proteins.faa` when SignalP
  predicts secreted candidate proteins (signal peptide removed)
- `outputs/task/candidate_sequences/candidate_gene_evidence.tsv`
- `outputs/task/summary/high_confidence_candidate_summary.tsv`
- `outputs/task/summary/final_target_candidates.tsv`
- `outputs/task/summary/experimental_hypotheses.tsv`
