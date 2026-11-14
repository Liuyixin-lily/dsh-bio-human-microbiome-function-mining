---
name: intake-environment
description: >-
  Ask the user for their execution environment — host, tool paths, required
  environment variables, databases, data locations and permission to execute —
  then verify what is actually reachable before running any workflow.
language: mixed
category: guide
---

# Intake Environment

Load this skill **before running any tool**, on every new task. It answers "can I actually
run this, and am I allowed to?" — as opposed to `preflight_inputs.py`, which answers "are
the task inputs present?".

**It comes after the target, not before it.** Settle what is being screened (entry A with an
EC / reaction / sequence, or entry B from the library) first, then scope the questionnaire to
what that target needs:

```bash
python3 scripts/intake_environment.py --ask --task card        # no external software at all
python3 scripts/intake_environment.py --ask --task screening   # DIAMOND + CD-HIT
python3 scripts/intake_environment.py --ask --task structure   # + US-align, structure source
python3 scripts/intake_environment.py --ask                    # full six groups
python3 scripts/intake_environment.py --ask --task full        # everything incl. Bakta/FedKEA/DEER
```

Asking for a server, a Bakta database and a DEER checkpoint before knowing whether the task
touches a genome makes the user answer questions about paths that will never be used. Two
orders are easy to confuse:

- **conversation order**: target first, then the environment needed for it;
- **execution order**: nothing runs until the environment is verified.

Scope only the *conversation*. The execution rule never relaxes.

## Why this exists

The expensive failures in this workflow are environmental, not scientific. Real
examples from one project:

- a tool invoked by absolute path without its conda env on `PATH` (`foldseek: command
  not found`, exit 127);
- a tool needing `PYTHONPATH` so its own package imports resolve;
- a tool hanging in `__inet_stream_connect` because it tried to fetch a checkpoint
  from Hugging Face on a machine with **no network**;
- a Bakta run that could not start because `BAKTA_DB_FULL` was never set;
- a shared box already running 146 processes from another project, so throughput
  assumptions were wrong.

None of these is discoverable from the science; all are discoverable by asking.

## Step 1 — ask, do not assume

```bash
python3 scripts/intake_environment.py --ask
```

Send that questionnaire to the user verbatim. Do **not** infer answers from the repo,
from a previous task, or from what usually exists. Six groups:

1. **where** it runs (local / remote host+user / user runs it themselves) and whether
   you are allowed to execute there at all;
2. **machine** resources (cores, memory, GPU, scheduler, shared or not);
3. **tools** — absolute paths for DIAMOND, CD-HIT, US-align, DEER, FedKEA, Bakta,
   SignalP, hmmsearch, ESMFold, plus any conda env or env var each one needs;
4. **databases** — Bakta full/light, AlphaFold DB, PDB mirror, UniProt, FedKEA
   weights, DEER checkpoint;
5. **data** — candidate proteome/genome/annotation/structure paths, target structure;
6. **constraints** — network availability, disk quota, job time limit.

Missing answers stay `unknown`. Never fill them with a plausible default.

## Step 2 — record the answers

```bash
python3 scripts/intake_environment.py --init --output environment.json
```

The user (or you, transcribing their message) fills it in. A tool may be `null`
(absent), a string (path or command name), or an object
`{"path": "...", "env": {"LD_LIBRARY_PATH": "..."}}`.

## Step 3 — verify, then plan

```bash
python3 scripts/intake_environment.py --probe --config environment.json \
    --output-card environment_card.json --output-report environment_report.md
```

`--probe` runs each declared tool's version command and reports one of:

| status | meaning | what you may do |
| --- | --- | --- |
| `ready` | executable exists **and** reports a version containing a number | may run it, if execution is permitted |
| `unverified` | exists but cannot report a version, or a declared env path is missing | do not treat as usable; ask for confirmation or a smoke test |
| `missing` | declared but not found | hand over the exact command; do not run |
| `not_provided` | the user said they do not have it | give commands only |

Two rules that matter:

- **A path is not a working tool.** A binary that runs but prints no version is
  `unverified`, because the usual cause (wrong env, missing shared library) only
  shows up at run time.
- **Execution permission is separate from capability.** If
  `execution.allow_local_execution` is not `true`, produce a command list instead of
  running anything, no matter how ready the tools look.

When `execution.access` is `ssh`, also verify the host itself:

```bash
python3 scripts/intake_environment.py --probe --config environment.json \
    --check-ssh --output-card environment_card.json --output-report environment_report.md
```

`--check-ssh` does two things, because they fail differently: a TCP connect proves the
port is open, then a `BatchMode=yes` ssh proves the credentials already work without a
password prompt. It never prompts, never retries with a password and stores no
credentials. A host that is unreachable, or reachable but requiring interactive
authentication, is reported as such before any workflow is planned.

Add `--check-network` when the plan touches a downloader (AlphaFold DB, PDB, NCBI,
Hugging Face). If a host is unreachable, do not start a step that would auto-download.

## Step 4 — hand the verified paths to the project config

The same answers are what `project.json`'s `tools` block needs, so do not make the user
type them twice:

```bash
python3 scripts/intake_environment.py --probe --config environment.json \
    --output-card environment_card.json --emit-config outputs/task/config.tools.json
```

That fragment is generated under one rule: **a path is written only for a tool that came
back `ready`**. Everything else gets an empty `executable` with `enabled: false`, and a
note explaining why. Consequences worth knowing:

- `sequence_screen` stays disabled when CD-HIT is missing even if DIAMOND is ready —
  deduplication is a mandatory step, so the pair is the unit.
- a tool whose declared `LD_LIBRARY_PATH` / `PYTHONPATH` does not exist keeps its `env`
  block (so the user can see what to fix) but is not enabled.
- when execution permission was not explicitly granted, every `auto_run_local` is false.
- tools the bundled runners do not read (e.g. `hmmsearch`) are reported as notes instead
  of being invented into the schema.

Merge the fragment's `tools` and `inputs` keys into the project config. Because it is
generated rather than hand-written, re-run it whenever a path changes.

## Reporting back

Tell the user, in one short block:

- what is `ready`, what is `missing`, what is `unverified`;
- which workflow steps can therefore run now, and which degrade to "here is the command";
- what single answer would unblock the most (usually one tool path or one database path).

Then proceed with the main workflow, using the recorded environment. Re-run
`--probe` whenever the user changes a path or a new tool is needed.

## This is per-user, so nothing about it may be committed

`environment.json`, `environment_card.json`, `environment_report.md` and the emitted
`config.tools.json` describe **one machine**. They are generated locally, are in
`.gitignore`, and must never be filled in with your own paths and shared — the next
user has different ones.

What ships with the plugin is only the questionnaire and the empty skeleton (`--init`,
every field `null`). If you are extending the plugin and are tempted to "just fill it in
so the example works", use `/path/to/...` placeholders instead, then verify:

```bash
python3 scripts/intake_environment.py --audit-paths .
```

That audit fails on a real home directory (`/Users/<name>/`, `/home/<name>/`) or a private
IP address, and it runs in the test suite, so a demo config cannot quietly acquire one
person's paths again. Generic `/home/you/...` or `/path/to/...` placeholders are allowed.

## Guardrails

- Never claim a tool ran when it did not appear in `environment_card.json` as `ready`.
- Never silently substitute a different tool because the declared one is missing.
- Never assume the network is available.
- Keep `environment.json` free of secrets (passwords, tokens, API keys); record only
  paths and host/user names.
