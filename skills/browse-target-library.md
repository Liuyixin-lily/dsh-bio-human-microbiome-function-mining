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

## The library is optional

Nothing here is required for the plugin to work. With no library at all, entry A
(EC / reaction / sequence), per-site genome search, screening, literature evidence,
ranking and the CRO work order all still run. What the library adds is a menu of
"which enzymes are worth screening at this site", plus per-enzyme facts the
pre-screening ranker can derive scores from.

So: if `--list-domains` says the library is empty, that is a **supported state**,
not a broken install. Take the user to entry A or to `genome-search --source
<site>`, and only build a domain when they want durable coverage.

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

### 4b. If the user cannot choose between several candidates

Sometimes the process is clear but there are many enzymes, or the user asks
"should I look at *Cutibacterium* or *Staphylococcus* first?". The library gives a
curated `priority` / `attention` hint, but not a defensible ordering across many
candidates. For that, use the pre-screening ranker:

```bash
# start from the library so nobody retypes target ids and EC numbers
python3 scripts/score_target_priorities.py \
    --seed-from-library library/skin.json --output outputs/task/priorities

# fill the 0-5 scores in the two seed tables, then rank
python3 scripts/score_target_priorities.py \
    --enzymes outputs/task/priorities/enzyme_registry.seed.tsv \
    --taxa outputs/task/priorities/taxa_registry.seed.tsv \
    --site skin --output outputs/task/priorities
```

Outputs: `enzyme_priority_ranking.tsv`, `taxa_priority_ranking.tsv`,
`selected_taxa.tsv`, `selected_taxa.txt`, `ranking_report.md`.

`selected_taxa.txt` feeds genome search directly:

```bash
python3 skills/genome-search/scripts/genome_source_search.py taxa \
    --input outputs/task/priorities/selected_taxa.txt --source skin \
    --out-xlsx work/genome_search/skin.xlsx --out-tsv work/genome_search/skin.tsv
```

The scoring weights are the "standard"; the component scores are inputs. Most of
them are **computable from artifacts the plugin already has**, so do not ask the
user to hand-type all twelve:

```bash
python3 scripts/score_target_priorities.py \
    --enzymes outputs/task/priorities/enzyme_registry.seed.tsv \
    --library library/skin.json \
    --reference-enzymes outputs/reference/reference_enzyme_set.tsv \
    --genomes work/genome_search/skin.tsv \
    --auto-score --site skin --output outputs/task/priorities
```

With `--auto-score`, `biochemical_clarity_score`, `microbial_plausibility_score` and
`novelty_score` come from the library entry, `sequence_structure_score` from the
reference enzyme set, and `genome_availability_score` / `site_presence_score` from the
genome-search table. Every derived cell records its rubric in `score_sources`
(`auto:library`, `auto:reference_enzymes`, `auto:genome_search`).

Two more scores come from a real literature table, so run `literature-evidence`
first when the ranking matters:

```bash
python3 scripts/score_target_priorities.py \
    --enzymes outputs/task/priorities/enzyme_registry.seed.tsv \
    --library library/skin.json \
    --literature outputs/task/literature_evidence.tsv \
    --disease "atopic dermatitis" \
    --auto-score --site skin --output outputs/task/priorities
```

- `site_evidence_score`: counts **verified** functional records
  (`verified=yes` and `evidence_type` in `direct_functional_evidence` /
  `related_assay`): 1 → 3, 2 → 4, ≥3 → 5. Only reviews → 2. Unverified records and
  `no_evidence` rows score nothing at all — they are not evidence.
- `disease_relevance_score`: requires `--disease`. Counts verified records whose
  title/finding/search string names that phenotype: ≥2 → 4, 1 → 3, and 1 when the
  search produced usable records but none link to it (`auto:literature:no_match`).
  This is **co-occurrence, not causality** — say so when presenting it.

If a target has no usable verified record, both cells stay gaps rather than becoming
0: absence of evidence is not evidence of absence. The report prints exactly which
references were counted, with their evidence types and verified flags.

What is left for the user is then genuinely narrow: assay feasibility, metabolic
plausibility, strain accessibility. The script refuses to rank while a required cell
is neither given nor derivable, and it names the missing cells plus the flag that
would make each one derivable.

Rules for this ranking, because it is easy to over-read:

- **Every component score is human judgement**, not a measurement. It says "do
  this first", never "this has the function". Say that out loud to the user.
- The scoring weights and the exact policy are written into every row
  (`scoring_policy`), so a ranking can be recomputed and challenged.
- A shortlist is not an evidence table. It never replaces sequence, structure,
  annotation or literature evidence.
- If the script reports that the selection threshold is unreachable, that is a
  config bug to fix — not a finding that nothing is worth doing.
- Registries written for the original skin-only `select-candidate` skill are
  accepted as-is: `skin_process` / `skin_evidence_score` / `skin_presence_score`
  are read as aliases.

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

## The full B route, and where it hands off to A

Entry B is a front end, not a terminus. Three scripts cover it end to end:

```bash
# 1) focus phrase only -> menu, route, literature for every candidate, then the recommendation tables
python3 scripts/run_entry_b.py --topic "皮肤外源性物质代谢" --site skin \
    --output-dir outputs/task/entry_b

# 2) the library misses: let the candidates themselves come from literature
python3 scripts/discover_enzyme_candidates.py --site skin \
    --terms "skin microbiome xenobiotic metabolism enzyme" --limit 25 \
    --output outputs/task/discovery/enzyme_registry.tsv \
    --evidence outputs/task/discovery/literature_evidence.tsv

# 3) merge several registries + a taxa list into the two recommendation tables
python3 scripts/build_candidate_shortlist.py --site skin \
    --enzymes <registry>.tsv --taxa <site>_taxa_registry.tsv --library library/<domain>.json \
    --output-dir outputs/task/candidates
```

A library hit does **not** end the retrieval: for every candidate in the seeded registry entry B runs
`literature_for_registry.py`, which retrieves per candidate, classifies what the abstract actually says
(activity/method words promote it to `direct_functional_evidence`, otherwise `review`) and runs a
second, structure-targeted query (`"<enzyme> crystal structure"`) because a topic query almost never
names a structure. Those rows are what `site_evidence`, `assay_feasibility` and `sequence_structure`
are computed from — skipping the step is why a shortlist reads 1.5/5. `--skip-discovery` turns it off
for an offline run, and a query that finds records but resolves no identifier is reported as a failed
lookup rather than silently scored as absent evidence.

The tables are `recommended_enzymes.tsv` / `recommended_taxa.tsv`. Taxa are recommended when the
ranking's own threshold is met (`priority_score >= 3.0`, i.e. `selection_status=selected`); enzymes
carry no pass mark, so their table is the ranked rows with at least two scored components. The full
pool is in `candidate_enzymes.tsv` / `candidate_taxa.tsv`. Ordering is evidence tier first, then
score: a hand-scored entry with no references must not outrank one with references.

Once the user picks a row, hand off to entry A — same command, no re-derivation:

```bash
python3 scripts/run_entry_b.py --topic "<same topic>" --site skin \
    --select <target_id> --ec <EC> --proteome <candidate proteome>.faa --output-dir outputs/task/entry_b
```

A family name is not a target: one family maps to several ECs, so `--select` without `--ec` stops and
asks. Do not choose the EC for the user.
