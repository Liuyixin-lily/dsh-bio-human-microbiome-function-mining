# Literature Evidence

This note explains how the plugin adds a traceable literature evidence chain
after candidate screening and before final experimental design.

The plugin does not bundle a literature search implementation. It routes the
search and audit work through the `nature-academic-search` skill when that
skill and its MCP literature servers are available and the user allows direct
execution.

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
