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
npx -y @deepseek-ai/dsh plugin --profile web add github:your-scope/human-microbiome-function-mining
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

After this, start a new agent/assistant session and confirm the plugin skill
`functional-dark-matter-discover` is available.

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

## 4. Use the plugin on your own data

1. Copy the plugin into your DeepSeek harness environment.
2. Create a project configuration:

```bash
cp human_microbiome_function_mining/config.minimal.example.json project.json
```

3. Edit `project.json` with:
   - target enzyme FASTA and target structure PDB, or an EC/reaction
   - candidate proteome FASTA, optional `.gbff`
   - candidate structure directory, optional
   - tool paths: DIAMOND, CD-HIT, US-align, optional DEER/FedKEA/Bakta
   - literature sources: MCP literature tools when available, otherwise the
     plugin will give you search terms or accept user-provided verified
     citation files

4. Ask the DeepSeek agent to run the workflow. The agent can execute configured
   tools when they are accessible from the current terminal. If a tool is not
   accessible, the agent prints the exact command for you to run on your own
   compute and then consumes the returned files.

## 5. External tools are yours, the plugin is not a tool installer

This plugin does not bundle DIAMOND, US-align, DEER, FedKEA, or Bakta. You are
expected to provide your own dataset and compute. If you already have those
tools on your server, give the plugin their paths in `project.json`.

External tool sources:

- DEER: <https://github.com/WangJiuming/deer>
- FedKEA local: <https://github.com/Stevenleizheng/FEDKEA>
- FedKEA web (manual submission): <https://www.viromelab.com/software/fedkea>

## 6. Final ranked outputs after scoring

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
- `outputs/task/candidate_sequences/candidate_gene_evidence.tsv`
- `outputs/task/summary/high_confidence_candidate_summary.tsv`
- `outputs/task/summary/final_target_candidates.tsv`
- `outputs/task/summary/experimental_hypotheses.tsv`
