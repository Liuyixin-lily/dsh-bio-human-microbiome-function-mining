---
name: browse-target-library
description: >-
  Turn a vague natural-language interest ("skin metabolism", "油脂分泌", "which
  microbes matter for body odour") into a pickable list of physiological
  processes, taxa, and enzyme targets, then materialize the chosen target as a
  Target Function Card.
language: mixed
category: planning
---

# Browse Target Library

Use this skill **only when the user cannot name the target yet**. Typical user
statements that land here:

- "皮肤代谢有哪些重要的生理过程？"
- "我关注油脂分泌，有哪些菌 / 哪些酶值得看？"
- "都有哪些关注的菌？"
- "想研究皮肤菌对屏障的影响"
- "肠道菌有哪些代谢值得做？"
- any single keyword such as 体味, 头皮屑, 痤疮, 短链脂肪酸, TMAO

The job of this skill is to move the user from interest to a chosen enzyme target
**without inventing targets** and **without pretending the library is evidence**.

## When NOT to use this skill

`browse-target-library` and `build-target-function-card` are two **peer entries**,
not two stages. The library is not a mandatory first step, and it is not a gate in
front of explicit input. Skip this skill entirely — go straight to
`build-target-function-card` — whenever the user already gives any of:

- an enzyme name or a curated target name ("神经酰胺酶", "cutinase", "AANAT")
- an EC number, full or family-level ("3.1.4.12", "3.1.1.-")
- a substrate-product reaction ("sphingomyelin + H2O -> ceramide + phosphocholine")
- a protein sequence, a FASTA path, or a PDB/AlphaFold structure
- a project.json that already carries a target

In those cases the library adds a step and buys nothing. Only if the user is
stuck ("I care about oily skin, what is worth screening?") do you open the
library. Both entries converge on `target_function_card.json`; everything after
that is identical, so the only question is which one matches what the user
already has.

If a user starts vague and then names the enzyme themselves, stop browsing and
switch to `build-target-function-card` immediately — do not keep showing menus.

## What the library is

`library/<domain>.json` holds a three-level curated index:

```
domain (body site)  ->  process (physiological process)  ->  enzyme (screening target)
```

Each enzyme target carries: EC number and its confidence, reaction, substrate,
product, cofactor, fold hint, known microbial examples, a recommended workflow
**entry point** (`reaction` / `ec` / `sequence`), a `dark_matter` flag, a priority,
a provenance note, and the experiment that would falsify the proposed function.

`library/skin.json` is `curated`; `library/gut.json` is `starter`. Treat `starter`
as a seed list and say so out loud.

## Workflow

### 1. Locate the user's words in the library

```bash
python3 scripts/browse_target_library.py --search "<the user's own words>"
```

Search both Chinese and English phrasing; query 2–3 variants when the first miss
is uninformative. `--json` gives machine-readable hits when you need to build a
choice list.

### 2. If the body site is still unknown, ask for it first

```bash
python3 scripts/browse_target_library.py --list-domains
```

Ask **one** question: which body site / niche. Do not ask for an enzyme name at
this point — that only pushes the burden back onto the user.

The three layers are independently listable, so answer the question the user
actually asked instead of forcing them down to an enzyme:

```bash
--list-taxa skin        # "都有哪些关注的菌"  -> taxon, Chinese name, attention, role, processes
--list-processes skin   # "有哪些重要的生理过程" -> process list with their enzyme targets
--show <id>             # expand one domain / process / enzyme
```

### 2b. Recognise a "what is in the library" question

Queries like "都有哪些关注的菌" or "哪些酶值得关注" name no topic at all. `--search`
detects that and prints the library menu instead of a "no hit" dead end. Follow
its pointers (`--list-taxa` / `--list-processes`) rather than inventing an answer,
and keep the domain question open until the user names a body site.

### 3. Present the processes, not the enzymes

When the user asks "有哪些重要的生理过程", show the process layer:

```bash
python3 scripts/browse_target_library.py --list-processes <domain>
```

Render each option as **one line of plain language + why it matters**, numbered.
Keep it to about ten options. If the harness has a question/choice tool (for
example `ask_user_question`), use it to hand the numbered options over; otherwise
print the numbered menu and wait for the user's number.

Never silently pick a process for the user. If the user genuinely has no
preference, say which two you would start with and why, then ask.

### 4. Expand the chosen process

```bash
python3 scripts/browse_target_library.py --show <process_id>
```

Show: the process, its key taxa, and each enzyme target with its EC, whether it
is dark matter, and its recommended entry point. Explain the entry-point choice
in one sentence, because it decides the whole downstream route:

| entry_point | meaning | downstream route |
| --- | --- | --- |
| `reaction` | substrate and product are clear | build the card from the reaction, then sequence screen |
| `ec` | a complete EC number exists | build the card from the EC and fetch reference enzymes by EC |
| `sequence` | no EC, or no characterized representative | start from a known sequence / structure, sequence + structure screening both matter |

### 5. Materialize the selection

After the user confirms one enzyme target:

```bash
python3 scripts/browse_target_library.py --export-card <enzyme_id> --output-dir <project_dir>
```

This writes `target_function_card.json` (with `input_source: library`,
`library_id`, `library_version`) and `target_selection.md` (the human rationale:
key taxa, entry point, evidence status, falsifying experiment).

Then hand the card to `build-target-function-card` to review the fields, and
continue with the main workflow using the recorded entry point.

## Missing from the library: escalate, never improvise

`--search` returning no hit is an **informative miss**, not a blocker and not an
answer. The library is content, not a capability boundary: it ships two body
sites, but the plugin's mechanisms are site-generic. Say clearly "库里没有这条，
只代表尚未策展", then escalate in this order:

### 1. Route the question

```bash
python3 scripts/resolve_target_intent.py --query "<the user's own words>"
```

It classifies the question (EC / reaction / taxon / body site / phenotype),
checks library coverage **at the named body site**, and prints executable steps.
Follow its plan instead of inventing one. Key behaviours it already implements:

- an EC number, reaction, or sequence routes to entry A and skips the library;
- a taxon routes to genome assembly selection (`genome_source_search.py`, which
  already supports skin / oral / gut / respiratory / urogenital / blood /
  environment);
- a site or phenotype the library does not cover routes to literature search terms
  plus a narrowing step;
- **a library hit at a different body site is reported as an analogy only.** Never
  answer "阴道菌群" with the skin acidification process just because both mention
  acid.

### 2. If the user can actually name a target, leave the library

Go straight to `build-target-function-card`. Do not expand the library just to
reach a target you already have.

### 3. If the direction deserves durable coverage, build a starter domain

```bash
python3 scripts/build_library_domain.py --init --domain oral --output specs/oral.json
# fill the spec with facts you can actually source, then:
python3 scripts/build_library_domain.py --build --spec specs/oral.json --output library/oral.json
python3 scripts/browse_target_library.py --validate
```

The builder enforces the honesty rules in code, so a generated domain cannot
pretend to be curated and cannot carry citations: empty fields are a hard error,
`content_status` is forced to `starter`, `evidence_refs` is forced empty, and
`provenance_source` is required per enzyme.

Never write a library entry from memory alone. No fabricated EC numbers, gene
symbols, UniProt/PDB accessions, or PMID/DOI.

## Guardrails

- The library is a **curated prior** (`evidence_status: curated_prior`). Do not
  describe an entry as "已证明", and do not upgrade it to `literature_verified`
  yourself — only `literature-evidence` may do that, after it has real identifiers.
- Do not fill `evidence_refs`. `--validate` rejects `literature_verified` with
  empty or malformed identifiers.
- `dark_matter: true` targets must keep `ec_confidence: none` and an empty `ec`.
  Do not borrow a neighbouring enzyme's EC number to make the table look tidy.
- One question at a time. Process selection, then enzyme selection, then entry
  point confirmation — not all three at once.
- If the `starter` domain is in play, state which processes are missing so the
  user does not over-read the list.
- Keep the user's own wording for the phenotype they care about (油脂分泌 / 体味 /
  头皮屑 …), and map it to the process id — do not silently replace their term
  with jargon.

## Outputs

| File | Purpose |
| --- | --- |
| `target_function_card.json` | the selected target, directly consumable downstream |
| `target_selection.md` | why this target, key taxa, entry point, evidence status, falsifying experiment |
| optional `target_library.tsv` | whole library flattened for review / manual ticking |

## Audit the library itself

```bash
python3 scripts/browse_target_library.py --validate
```

Checks required fields, id collisions, EC/`ec_confidence` consistency, entry-point
and evidence enums, `key_taxa` cross-references, empty `literature_verified`, and
malformed identifiers.
