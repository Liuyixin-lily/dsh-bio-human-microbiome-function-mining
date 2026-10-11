# Tool Execution Boundary

This plugin is a scientific protocol and evidence-integration layer. It does
not own a remote cluster. The Agent can only run a tool when the tool executable
and its input files are accessible from the current terminal, for example when
the user is already connected to their own server and Codex runs in that
environment.

When a workflow needs an external tool, the Agent follows this order:

1. Read the user-supplied tool paths and data paths from `project.json`/
   `config.example.json`. **For every path that is missing, still an example
   placeholder (`/path/to/...`), or on a different host, ask the user for the
   concrete location before doing anything else** - the exact executable, script
   or database directory, the output directory, compute parameters, and whether
   the Agent may run it (`auto_run_local`). Work through the checklist in
   `input_paths.md` and ask for all of it in one message rather than one item at
   a time. Ask the user to run `command -v <tool>` if they do not know a path.
   Never invent or guess a path.
2. If the data or tools are on a **remote host** rather than this machine, ask
   for `user@host` and the absolute path there, record both, and confirm access
   before running anything. A path that is absent locally is not thereby missing
   - it may simply live on the other machine.
3. Check whether the executable exists/is callable and whether required inputs
   exist from the current terminal (`command -v`, `test -f`, `ls`, etc.), or run
   `scripts/preflight_inputs.py --project project.json --require-tools`, which
   reports `ok` / `placeholder` / `missing` / `invalid` for each configured data
   and tool path.
4. If accessible and `auto_run_local` is enabled, run the tool directly and
   record the command and version for provenance.
5. If accessible but the user wants only instructions, give the exact command
   and wait for the output files.
6. If not accessible from the current terminal, give the exact command/install
   notes for the user to run on their own compute and wait for returned output.
7. Validate that the returned output files exist and have the expected format.
8. Parse the returned output into the plugin's TSV schemas.
9. Merge that parsed evidence into `combined_candidates.tsv`.
10. Mark the evidence as pending when the user has not yet returned output.

Before heavy work, report the resolved split back to the user: which data and
tool paths are PROVIDED, which must still be ACQUIRED, and which exact commands
they will need to run themselves.

## FedKEA

- FedKEA source and local install:
  <https://github.com/Stevenleizheng/FEDKEA>
- FedKEA web server for manual submission:
  <https://www.viromelab.com/software/fedkea>

- If FedKEA is accessible from the current terminal, Agent may run it directly
  with the user-supplied `main.py` path and write results into
  `local_result_dir`.
- Otherwise, the user runs FedKEA locally on their own server, or submits the
  candidate proteome to the FedKEA web server manually. Recommend the web route
  when the candidate list has fewer than 20 sequences and the local software
  route when there are 20 or more sequences.
- Agent never calls the FedKEA web server programmatically.
- Agent only consumes saved FedKEA output files:
  `binary_result.txt`, `enzyme_result_with_probability.csv`,
  `enzyme_result_with_confidence.csv`.

### Local FedKEA conda environment notes

Verified against the FedKEA repository layout on the demo server. The FedKEA
`main.py` internally calls `python` for helper subprocesses, so the environment
must be active before running it. If the environment's `numpy`/`torch` fail
with missing `CXXABI_1.3.9` symbols, point `LD_LIBRARY_PATH` at that conda
environment's `lib` directory before starting the wrapper.

```bash
source /path/to/miniconda3/etc/profile.d/conda.sh
conda activate fedkea
export PATH="$CONDA_PREFIX/bin:$PATH"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:${LD_LIBRARY_PATH:-}"
```

These environment variables can also be recorded inside `project.json` under
`validation_inputs.fedkea.env`, for example:

```json
"env": {
  "PATH": "/home/liuyixin/miniconda3/envs/fedkea/bin:/usr/local/bin:/usr/bin:/bin",
  "LD_LIBRARY_PATH": "/home/liuyixin/miniconda3/envs/fedkea/lib"
}
```

The wrapper accepts repeatable `--env-var NAME=VALUE` flags for ad-hoc runs
without editing the project file.

The FedKEA local path was tested on the demo server
(`172.16.100.7:/home/liuyixin/00.database/FEDKEA`) with the activation commands
above using three sequences from the upstream `Testset`. It completed all six
helper stages and the wrapper wrote `fedkea_results.tsv` with the expected
`binary_result.txt`, `enzyme_result_with_probability.csv`, and
`enzyme_result_with_confidence.csv` inputs.

## US-align

- Before US-align, check whether candidate structure files (PDB or CIF) exist
  for the sequence-filtered candidates.
- If a candidate lacks a structure file, run the bundled `structure-prediction`
  sub-skill to retrieve known structures or predict missing structures. Priority
  for final structures: experimental PDB > AlphaFold DB model passing
  `mean pLDDT >= 60` > homology model > de novo prediction. Continue only after
  the candidate structures are materialized as `structure/<protein_sequence_id>.pdb`.
- If the `USalign` executable and candidate/target structures are accessible
  from the current terminal, Agent may run the configured batch command
  directly and consume its output.
- Otherwise, the user runs US-align on their compute resources and returns its
  `-outfmt 2` text output.
- Agent parses that output with `scripts/parse_usalign.py` into
  `structural_hits.tsv` and `structural_candidates.tsv`.
- Agent must not run US-align when candidate structures are missing; the bundled
  `structure-prediction` sub-skill must come first.

## DEER

- DEER source and local install:
  <https://github.com/WangJiuming/deer>

- DEER is a fallback only.
- Use DEER when US-align does not produce enough suitable candidates. The
  `scripts/run_deer.py` wrapper automatically detects which configured source
  genome has zero US-align structural candidates and triggers DEER for that
  genome, after the user agrees and only when `deer.enabled` is true.
- Agent may use `scripts/run_deer.py` only when `script_path`,
  `template_pdb_dir`, `database_pdb_dir`, and the executable are accessible and
  a previous US-align output is visible, unless the user explicitly agrees to
  skip that gate and passes `--allow-without-usalign`.
- Otherwise, the user installs and runs DEER on their own compute and returns
  its output.
- DEER results are recorded per missing-candidate genome under
  `deer.output_dir/<genome_slug>/`, and a `deer_trigger_summary.tsv` lists the
  triggered genomes, status, and command.
- Agent consumes DEER output as additional structure evidence, never as a
  replacement for US-align.

## General rule

The Agent must not claim a tool was run unless it actually saw the output or ran
the command itself. When the tool is not accessible from the current terminal,
it should tell the user what command to run and what files to provide back.
