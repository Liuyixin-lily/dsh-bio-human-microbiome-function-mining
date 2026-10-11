# Literature Evidence

This note explains how the plugin adds a traceable literature evidence chain
after candidate screening and before final experimental design.

The plugin does not bundle a literature search implementation. It routes the
search and audit work through the `nature-academic-search` skill when that
skill and its MCP literature servers are available and the user allows direct
execution.

## Executable bridge

Because a prose-only delegation is fragile (the agent must know where the skill
lives and must pick a new-enough Python), the plugin ships
`scripts/run_literature_search.sh`. It:

- finds `nature-academic-search` via `NATURE_ACADEMIC_SEARCH_DIR`, the plugin
  tree, `~/.codex/skills`, `~/.dsh/skills`, or `~/.config/dsh/skills`;
- picks a Python >= 3.10 (the skill's `academic_search.py` uses PEP-604 unions
  and crashes on 3.9) via `LITERATURE_PYTHON` or auto-discovery;
- pipes hits through `scripts/resolve_literature_hits.py`, which converts
  DOIs to **verified PMIDs** and fetches **abstracts** from PubMed XML.

```bash
bash scripts/run_literature_search.sh --check
bash scripts/run_literature_search.sh "<query>" --limit 10 --resolve
bash scripts/run_literature_search.sh --doi 10.1016/j.chom.2022.01.004
```

If the skill is absent, the wrapper exits non-zero with the searched paths and a
remedy. Then fall back to the manual route in point 2 or 3 below.

## Routes

1. **MCP available (default when configured and allowed)**
   - Use `nature-academic-search` `multi-source-search` for enzyme/method,
     assay, mutation, catalytic-residue, and structural-biochemistry papers.
   - Use `nature-academic-search` `candidate-evidence-audit` when the user
     wants direct functional evidence screening for candidate organisms.
2. **MCP unavailable**
   - Use the no-MCP fallback in `nature-academic-search`
     (`scripts/academic_search.py`), which is limited and may only cover
     OpenAlex-style metadata.
   - Or give the user exact PubMed / Google Scholar search terms and wait for
     them to return verified citation files (`.nbib`, `.ris`, `.bib`).
3. **User-provided verified citations**
   - Parse `.nbib` / `.ris` / `.bib` files into `literature_evidence.tsv`.
   - Treat user-provided references as candidate evidence only after checking
     that required metadata fields are present and non-fabricated.

## What to search

For each target function:

- target enzyme name and EC number
- known catalytic residues and active-site studies
- compatible assays, substrates, products, and detection methods
- published mutation-validation studies

For each candidate organism or strain:

- published evidence that this organism produces or secretes the target enzyme
- direct functional evidence versus related phospholipase or esterase activity
- existing experimental validation of homologs that supports or opposes the
  candidate hypothesis

## Mandatory search coverage and triage

Search by at least three shapes, not just the enzyme name:

1. `<enzyme name>` AND `<genus species>`
2. `<genus species>` AND (`<expected product>` OR `<pathway>` OR `<phenotype>`)
3. `<gene name>` AND `<genus species>`

Then **read the abstract of every hit before classifying it**. Titles routinely
omit the mechanism: PMID 35123653 is titled "*Commensal Staphylococcus
epidermidis contributes to skin barrier homeostasis by generating protective
ceramides*", contains no occurrence of "sphingomyelinase", and yet directly
proves the sphingomyelin -> ceramide + phosphocholine reaction in this species.
An under-specified search once produced a false `no_evidence` verdict for exactly
this reason. Record the queries used in `source_search` so a negative result is
auditable.

## Output contract

Write `literature_evidence.tsv` with these columns:

| Column | Meaning |
| --- | --- |
| `candidate_id` | Candidate row identifier |
| `protein_accession` | Protein accession when applicable |
| `organism_or_strain` | Source organism for the candidate |
| `evidence_type` | `direct_functional_evidence`, `related_assay`, `catalytic_residue`, `review`, `no_evidence` |
| `reference_type` | `PMID`, `DOI`, `URL`, or `manual` |
| `reference_id` | Verified PMID/DOI/URL |
| `title` | Paper title |
| `first_author` | First author surname, or empty |
| `journal` | Journal or preprint server |
| `year` | Publication year |
| `finding` | One-sentence finding |
| `verified` | `yes` or `no` |
| `source_search` | Search terms or search route used |
| `notes` | Additional traceability notes |

## Candidate-table fields

The candidate table schema `schemas/combined_candidates.schema.tsv` supports
the following `literature_*` fields:

- `literature_evidence_file`
- `literature_evidence_count`
- `literature_direct_functional`
- `literature_assay_hits`
- `literature_catalytic_residue`
- `literature_main_findings`
- `literature_verified_refs`

Leave these fields empty when no verified literature is available. Never
populate them with unverified PMID/DOI identifiers.

## Guardrails

- Do not fabricate any reference or finding.
- Do not claim full PubMed coverage when MCP tools are unavailable.
- Do not use literature as a replacement for wet-lab activity validation.
- If a candidate organism has direct and proven target function, record it as
  `direct_functional_evidence` and flag it in `literature_main_findings` so the
  final ranking can consider that evidence explicitly.
