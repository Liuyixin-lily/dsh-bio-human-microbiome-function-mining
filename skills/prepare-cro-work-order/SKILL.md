---
name: prepare-cro-work-order
description: >-
  Turn a validated target and candidate list into a vendor-facing contract
  research work order: quotable modules from gene synthesis through enzyme
  assays, verbatim sequences, pre-registered decision rules, a glossary for
  non-specialists, and a "confirm before sending" checklist.
metadata:
  short-description: Write a work order a company can quote and execute
---

# Prepare CRO Work Order

Use this skill when the user wants to **hand the wet lab to someone else** and
says anything like:

- "我不是很懂分子生物学，帮我写一份能直接发给公司的实验方案"
- "我要外包基因合成 / 表达纯化 / 酶活检测，怎么给公司下单？"
- "给我一份可以发给 CRO 的实验设计，我要去询价"
- "这份设计我要直接转给别人做，需要写清楚交付什么"

This is **not** the same deliverable as `experimental_design.md` from
`summarize_candidates.py`. That document is written for people who will run the
bench work themselves. This skill produces a **purchasing document**: a module
split the vendor can quote line by line, with deliverables, acceptance criteria,
and the confirmation items that must be settled before work starts.

## Prerequisites

| Input | Required | Why |
| --- | --- | --- |
| `target_function_card.json` | yes | defines what is being tested |
| `final_target_candidates.tsv` (or a scored table) | yes for `candidates`/`full` scope | the proteins to synthesize |
| candidate protein FASTA | yes for gene synthesis | sequences are copied verbatim; never invented |
| `experimental_hypotheses.tsv` | strongly recommended | supplies the pre-registered decision rule |

If a prerequisite is missing, produce the package anyway and let
`cro_gap_list.md` carry the gap. Do **not** fill a missing sequence with a
placeholder.

## Command

```bash
python3 scripts/build_cro_work_order.py \
  --card outputs/task/target_function_card.json \
  --candidates outputs/task/summary/final_target_candidates.tsv \
  --hypotheses outputs/task/summary/experimental_hypotheses.tsv \
  --sequences outputs/task/candidate_sequences/candidate_proteins.faa \
  --outdir outputs/task/cro_package \
  --scope candidates \
  --bsl BSL-1
```

### Choosing `--scope`

| scope | Modules | Use when |
| --- | --- | --- |
| `assay_first` | M1 M3 M4 M5 M7 M10 | no candidates yet, or the assay itself is unproven. Build the assay with a positive control first, so screening results are not blocked on method development. |
| `candidates` | + M6 | default; candidates are known and you want parallel activity data |
| `full` | + M2 M8 M9 | also want catalytic-residue mutants, substrate spectrum / kinetics, and optional cell or strain-level validation |

Recommend `assay_first` explicitly when the candidate list is empty. Do not
silently quote the full package for someone who has no sequences yet.

### Module set

| id | module |
| --- | --- |
| M1 | gene synthesis, codon optimization, cloning |
| M2 | catalytic-residue mutants (negative controls) |
| M3 | small-scale expression and solubility check |
| M4 | scale-up expression and purification |
| M5 | assay development with a positive control |
| M6 | parallel activity assay across candidates |
| M7 | controls and artefact exclusion |
| M8 | extended characterization (substrate spectrum, pH/temperature, kinetics) |
| M9 | cell or strain-level validation (needs a specialist CRO) |
| M10 | data delivery, biosafety, IP |

## Outputs

| File | Purpose |
| --- | --- |
| `cro_work_order.md` | the vendor-facing document: objective, module table, candidate list with sequence status, sequence appendix note, controls, pre-registered decision rules, "confirm before sending", glossary, RFQ questions, boundary statement |
| `cro_modules.tsv` | quotable module table, one row per module |
| `cro_sequences.faa` | sequences copied **verbatim** from the candidate FASTA, with provenance in the header |
| `cro_sequences.MISSING.md` | written instead of the FASTA when no sequence is available |
| `cro_gap_list.md` | the items that must be resolved before the package can be sent |

## Guardrails

- **No prices, no turnaround times, no vendor names, no catalogue numbers.**
  Those cells read `需询价 / quote required` and `待公司填写 / TBD`. Inventing a
  number here would be worse than leaving it blank, because the user might budget
  against it.
- **No invented sequences.** Sequences are copied only from a FASTA the user
  already has; the script verifies nothing, so it must be byte-faithful. When
  none exist it writes `cro_sequences.MISSING.md` rather than a plausible
  placeholder — a fake sequence sent to a synthesis vendor wastes an entire batch.
- **Biosafety is a checklist, not a conclusion.** The document prefills a BSL
  level and lists the items the user's institutional biosafety committee must
  confirm. Never state that a project is compliant or exempt.
- **Decision rules are pre-registered.** They come from
  `experimental_hypotheses.tsv`. Keep them in the document as written; do not
  soften them after data arrive.
- **No functional conclusions.** The work order is a purchasing document. A
  candidate is not "confirmed" until the assays run and are independently
  repeatable.
- When a candidate has no sequence, say so in the candidate table (the
  `sequence_status` column) and in the gap list — do not quietly drop the row.

## After the vendor data comes back

1. Compare each candidate against its `falsification_criteria`, not against a
   fresh intuition.
2. Record a per-candidate verdict: 成立 / 不成立 / 不可判定. Use 不可判定 when the
   protein was insoluble, under-expressed, or a control failed — that is an
   experiment failure, not evidence of no function.
3. Only after independent replication may a candidate be described as having the
   activity. Update the evidence tables, not just the narrative.

## Related

- `summarize_candidates.py` produces the researcher-facing `experimental_design.md`
  and the hypotheses table this skill consumes.
- `literature-evidence` must still be run before the candidate set is sent out: a
  vendor will ask why these proteins, and the answer must be traceable.
