---
name: build-target-function-card
description: >-
  Normalize the user's target enzyme input into a machine-readable Target
  Function Card for downstream screening.
language: mixed
category: planning
---

# Build Target Function Card

Use this skill when the user supplies a target enzyme as a protein sequence, an
EC number, a substrate-product reaction, or a curated target name and the
workflow needs a stable normalized description before sequence screening.

## Inputs

Collect whatever the user provides, including when available:

- target enzyme name
- EC number
- reaction string
- substrate and product
- cofactor
- known catalytic residues or a path to a catalytic residue table
- known structural fold or target structure path
- target sequence or target sequence file path
- known human/microbial reference enzymes
- related metabolic pathway

## How to build the card

1. Assign a stable `target_id` using the enzyme or protein name when possible.
2. Fill every field in `target_function_card.json` according to the schema in
   `schemas/target_function_card.schema.json`.
3. Use empty strings for unknown optional literal fields.
4. Prefer a full EC number when the user supplies or validates one. Use a
   family-level value such as `3.1.1.-` when the full EC number is unknown.
5. Keep file paths as project-relative paths when they point to files inside the
   user's task directory.
6. Populate `known_enzymes` and `known_microbial_enzymes` only with identifiers
   or proteins that have explicit provenance. Do not invent IDs.
7. Record the original input form in `input_source`: `sequence`, `ec`,
   `reaction`, or `manual`.
8. Ask the user or mark validation gaps explicitly when critical fields such as
   the sequence file, EC number, or reaction are missing.

## Output

Write exactly one machine-readable result:

- `target_function_card.json`

Optionally write a short human-readable summary:

- `workflow_plan.md`

## Guardrails

- Do not fabricate UniProt, PDB, EC, KEGG, PubMed, or assembly identifiers.
- Do not claim a full EC number unless the user supplied it or a traceable
  database record supports it.
- Do not write a target function card that omits required schema fields.
- Do not run sequence or structure screening from this skill; that is handled by
  downstream skills.
- If information is missing, write the card with empty values and clearly list
  the inputs needed before screening.
