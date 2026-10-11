# Input Path Checklist

Use this file when a workflow needs the user's data or tools and they have not
been configured yet. Ask for **all** of it in one message rather than stalling
one item at a time, and report the resulting split back before running anything
heavy.

Every entry below maps to a real key in `project.json` /
`config.example.json`. Ask for the ones the chosen route actually needs; mark the
rest as not applicable rather than leaving them ambiguous.

## 1. Data locations

| What | `project.json` key | Needed when |
| --- | --- | --- |
| Candidate proteome FASTA | `inputs.candidate_proteome_fasta` | always (sequence screening) |
| Genome GenBank flat file | `inputs.candidate_annotation_gbff`, `candidate_sequences.genomes.<acc>.gbff` | annotation evidence / fast path |
| Genome CDS nucleotide FASTA | `candidate_sequences.genomes.<acc>.cds_fasta` | Bakta-free CDS route |
| Genome nucleotide FASTA | `candidate_sequences.genomes.<acc>.fna` | genome context |
| Target sequence FASTA | `inputs.target_sequence_fasta` | when the target is given as a sequence |
| Target structure PDB/CIF | `inputs.target_structure_pdb` | when US-align will be used |
| Candidate structure directory | `candidate_sequences.genomes.<acc>.structure_dir` | structure screening |
| Catalytic / pocket residue table | `inputs.target_catalytic_residues_file` | active-site comparison |

## 2. Software paths

Ask for the **executable, its version, and whether the Agent may run it**
(`auto_run_local`). A tool the Agent will not run locally still needs a path so
the user can run it themselves, but a missing path is then not fatal.

| Tool | `project.json` key | Notes |
| --- | --- | --- |
| DIAMOND | `tools.sequence_screen.executable` | required for sequence screening |
| CD-HIT | `tools.sequence_screen.cdhit_executable` | dedup before DIAMOND makedb |
| US-align | `tools.usalign.executable` | structure comparison |
| DEER | `tools.deer.executable` + `tools.deer.script_path` | fallback only |
| DEER checkpoint dir | `tools.deer.ckpt_dir` (+ `deer_model_path`) | DEER only |
| Bakta | `tools.bakta.executable` (or conda env + database) | genome annotation |
| SignalP | `tools.signalp.executable` | optional secretion analysis |
| FedKEA | `validation_inputs.fedkea.executable` + `script_path` | optional EC validation |

Never invent a path. If the user does not know it, ask them to run
`command -v <tool>` (or `which <tool>`) and paste the result.

## 3. Where the files live

`project.json` paths are resolved relative to the project directory. Two extra
cases must be asked about explicitly:

- **Remote host** - if the data or tools are on another machine (for example a
  lab server), ask for `user@host` and the **absolute path there**, and record
  both, e.g. `liuyixin@172.16.100.7:/home/liuyixin/database/HSMD/<species>/`.
  Do not silently assume the path is local, and do not treat a remote path as
  missing just because it does not exist on this machine.
- **User-supplied tool paths on that host** - the executable may only exist on
  the remote host. Say which commands will be run there and confirm access
  before running them.

## 4. Verify before spending compute

```bash
python3 scripts/preflight_inputs.py --project project.json --require-tools
```

Statuses reported for tool paths:

| Status | Meaning | Fix |
| --- | --- | --- |
| `ok` | resolves as a file, or on `PATH` | none |
| `placeholder` | still `/path/to/...` from the example config | user supplies the real path |
| `missing` | not found at that path or on `PATH` | install the tool, or give the correct path |
| `invalid` | exists but is not executable / wrong kind | fix permissions or the path |
| `optional_missing` | absent, but `auto_run_local` is false, so the user runs it | none; just confirm the intended command |

A `placeholder` or `missing` entry for a tool with `auto_run_local: true` is
fatal - resolve it with the user before starting heavy work.

## 5. What to report back

1. The PROVIDED / TO ACQUIRE split over data **and** tools.
2. Any path still holding an example placeholder.
3. For each tool the Agent will not run, the exact command the user must run.
4. Whether the route is local or remote, and the host involved.
