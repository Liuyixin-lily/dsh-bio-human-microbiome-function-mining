# Project files

This directory is a workspace placeholder for project-specific configuration
files used during acceptance runs or demonstrations. Demo project files are
not part of the delivered plugin package.

For a first run, copy `config.minimal.example.json` from the plugin root into
your own `project.json`. Alternatively, copy `config.example.json` when you
need DEER/FedKEA/Bakta or genome-prep fields. Update these fields before
running any wrapper:

- `inputs.*`
- `tools.*.executable`
- `tools.*.db` or data paths
- optional `validation_inputs.fedkea.local_result_dir`
- optional `candidate_sequences.candidates`

The project JSON is read by the wrapper scripts and by the agent workflow in
`references/workflow.md`.
