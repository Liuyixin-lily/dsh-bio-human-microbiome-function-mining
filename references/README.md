# References

This directory holds plugin-readable notes that tell DeepSeek and users how the
plugin maps to the existing workspace.

Intended files:

- `workflow.md`: the target workflow steps and expected intermediate files.
- `input_paths.md`: the checklist of data locations and software paths to ask the
  user for, including the remote-host convention and the `--require-tools` checks.
- `evidence_sources.md`: existing `data/`, `results/`, and `scripts/` files that
  can be used as input evidence.
- `thresholds.md`: the threshold policy used for sequence and structure screening.
- `tool_fallback.md`: when Agent can run external tools locally and how to
  fall back to exact user-run commands when tools/data are not accessible.
- `genome_dataset_preparation.md`: optional entry flow that runs the bundled
  `genome-search`, `genome-download`, and `genome-annotation` sub-skills when
  users start from taxa, source metadata, or accessions instead of an existing
  candidate proteome.
- `literature_evidence.md`: how the `literature-evidence` skill builds verified
  PMID/DOI evidence chains through MCP literature tools when available, or via
  OpenAlex-only discovery and user-provided citation files otherwise.
- `acceptance_criteria.md`: the checklist to close a task run with complete,
  traceable evidence.

These notes should be written so a new user with their own dataset can replace
paths while keeping the same protocol.

## Output schemas

Machine-readable output contracts live in `../schemas/`:

- `target_function_card.schema.json`
- `reference_enzyme_set.schema.tsv`
- `sequence_hits.schema.tsv`
- `structural_hits.schema.tsv`
- `sequence_candidates.schema.tsv`
- `structural_candidates.schema.tsv`
- `source_feature_annotations.schema.tsv`
- `combined_candidates.schema.tsv`

DeepSeek must follow these schemas whenever it writes generated task files.

When users provide `.faa` or `.gbff` candidate files that already carry protein
or CDS annotations, parse that existing evidence into
`source_feature_annotations.tsv` and merge it into `combined_candidates.tsv`
under the `source_*` fields. This is an existing-knowledge evidence chain, not a
replacement for sequence or structure screening.

For external validation tools such as FedKEA, record the source output path and
tool version in `combined_candidates.tsv` using the `fedkea_*` fields. Do not
summarize external results without keeping the original output file path.

## FedKEA outputs

FEDKEA can be used in either of these two ways:

1. **Local deployment on the user's own server**: use this route when the candidate
   list contains 20 or more sequences. The user installs FEDKEA according to
   its GitHub README, downloads the 5.6 GB model from Zenodo, and runs
   `python main.py -i candidate_proteome.faa -g '0' -b 64 -d data/ -o result/`.
   Agent reads the result files directly from the output directory.
2. **Web submission by the user**: use this route when the candidate list has fewer
   than 20 sequences. The user submits candidate protein sequences to the
   FedKEA web server, saves the returned result files, and provides those files to
   Agent. Agent parses them as long as the columns match the standard FedKEA output
   format.

FedKEA should be run on the candidate protein subset produced by sequence and
structure screening, not on the full proteome unless the user explicitly asks
for a whole-proteome scan. Candidate FASTA headers must keep the accession as
the first whitespace-delimited field with no description (for example
`>WP_...`). `parse_fedkea.py --expected-accessions` should be used to verify
that output accessions can be joined back to the submitted candidate IDs.

Agent must not claim to call the FedKEA web server programmatically. It should
only consume saved result files that the user provided or produced locally.

FEDKEA writes these files to the output directory:

- `binary_result.txt`: enzyme/non-enzyme prediction with columns `Accession`, `IsEnzyme`, `Probability`.
- `enzyme_result_with_probability.csv`: hierarchical EC number prediction with per-level probability columns.
- `enzyme_result_with_confidence.csv`: final EC prediction with columns `Accession`, `FinalResult`, `confidence`, `accepted_name`, `other_names`.

Map these into the `fedkea_*` fields in `combined_candidates.tsv`.

## Reference FedKEA local install

The FEDKEA GitHub repository is
<https://github.com/Stevenleizheng/FEDKEA>, and the web server for manual
submission is <https://www.viromelab.com/software/fedkea>. A local install
looks like:

```bash
git clone https://github.com/Stevenleizheng/FEDKEA.git
cd FEDKEA
conda create -n fedkea python=3.9
conda activate fedkea
```

Install PyTorch according to the server environment (CPU build or CUDA build).
Then install the remaining packages:

```bash
pip install fair-esm pandas biopython scikit-learn
```

Download and unpack the trained model:

```bash
wget -c https://zenodo.org/records/14868763/files/model_param.tar.gz
tar -xzvf model_param.tar.gz
```

Run prediction on the user's candidate protein FASTA:

```bash
python main.py -i candidate_proteome.faa -g '0' -b 64 -d data/ -o result/
```

Use `-g` with GPU IDs for GPU runs, or omit `-g` for CPU. `-t` can be used to
change the enzyme/non-enzyme threshold. The output directory contains
`binary_result.txt`, `enzyme_result_with_probability.csv`, and
`enzyme_result_with_confidence.csv`.

Because `main.py` starts helper subprocesses with `python`, run it from the
activated `fedkea` environment. If `numpy`/`torch` fail with missing
`CXXABI_1.3.9` symbols, also set `LD_LIBRARY_PATH` to the conda environment's
`lib` directory:

```bash
source /path/to/miniconda3/etc/profile.d/conda.sh
conda activate fedkea
export PATH="$CONDA_PREFIX/bin:$PATH"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:${LD_LIBRARY_PATH:-}"
```

These values can be encoded in `validation_inputs.fedkea.env` in a project
file, or passed ad hoc with repeatable `--env-var NAME=VALUE` flags when using
`run_fedkea.py`.

Do not include FedKEA output as proof of biochemical activity. Treat it as an
orthogonal computational validation layer.

The plugin includes `scripts/run_fedkea.py` as a wrapper around the local
FEDKEA `main.py` workflow above. It reads the `validation_inputs.fedkea`
section of `project.json`, runs `main.py` when the configured executable and
script path are accessible from the current terminal, then parses the output
directory into `fedkea_results.tsv`. When FEDKEA is not installed locally or
the user prefers the web route, the wrapper prints the exact command and waits
for the user to save the returned result files.
For the local route, set `validation_inputs.fedkea.expected_accessions` in
`project.json` or pass `--expected-accessions` so the parse step checks the
accession join before producing `fedkea_results.tsv`.
