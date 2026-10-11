# Human Microbiome Function Mining Codex Plugin

This is a Codex plugin copy of the existing DeepSeek Harness (dsh) package
`skin/human_microbiome_function_mining`. It carries the same skills, scripts,
schemas, references, preset files, and example project files.

The plugin turns a target enzyme input (UniProt/FASTA, EC number, substrate-product
reaction, or functional description) into candidate human microbiome proteins,
evidence tables, ranked candidates, falsifiable hypotheses, and wet-lab
experimental design.

## Boundaries

The plugin does not bundle or host heavy tools. DIAMOND, CD-HIT, US-align, DEER,
FedKEA, Bakta, PDB/AlphaFold databases, and literature databases must be provided
or accessed by the user, or run by an agent when tool executables and data paths
are available.

## Install as local plugin

To make this visible in Codex, the marketplace file should contain a local entry
with `source.path` pointing to this plugin directory. This workspace contains
`.agents/plugins/marketplace.json` with such an entry.

## Quick commands

```bash
python3 plugins/human-microbiome-function-mining/scripts/example_test.py
python3 plugins/human-microbiome-function-mining/scripts/validate_schema.py --root .
```

## Contents

- `.codex-plugin/plugin.json`: Codex plugin manifest
- `skills/`: Codex observable skills
- `scripts/`: helper scripts and parsers
- `schemas/`: TSV/JSON contract schemas
- `references/`: workflow thresholds and evidence rules
- `projects/`: example project configs
- `preset/`: original dsh agent preset files
- `demo/`: example demo outputs (not scientific evidence)
