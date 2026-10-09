---
name: literature-evidence
description: >-
  Search and audit published literature for existing functional evidence on the
  target enzyme and on each candidate protein or candidate organism. Supports
  multi-source literature search for assay, mutation, and known activity
  evidence, plus per-candidate organism direct-evidence audits.
language: mixed
category: evidence
---

# Literature Evidence

Use this skill after candidate screening has produced candidate proteins or
candidate organisms and before final candidate scoring or experimental design.
It adds a traceable literature evidence chain so experimental plans can cite
verified PMID/DOI sources instead of relying only on computational evidence.

**Tool boundary**: literature search is not bundled. Use the
`nature-academic-search` skill router when its MCP literature servers are
available and the user allows. If MCP is unavailable, use its no-MCP fallback
(OpenAlex-limited) or give the user exact PubMed / Google Scholar search terms
and wait for returned citations. Never fabricate PMID, DOI, title, journal,
year, or finding.

## Inputs

Read where available:

- `target_function_card.json`
- `sequence_candidates.tsv`
- `structural_candidates.tsv`
- `combined_candidates.tsv` or `scored_candidates_full.tsv`
- `candidate_sequences/candidate_proteins.faa`
- user-provided citation files (`.nbib`, `.ris`, `.bib`)
- `project.json` `literature_evidence` config block, if present

## Procedure

1. Detect the literature audit target:
   - **Enzyme evidence**: target EC number/name, reaction, known assay methods,
     catalytic-residue studies, mutation validation, and structural biochemistry.
   - **Candidate organism evidence**: for each candidate organism or strain,
     published evidence that it produces or secretes the target enzyme.
2. Follow `nature-academic-search` workflow routing.
   - Use `multi-source-search` for enzyme/method papers.
   - Use `candidate-evidence-audit` when the user needs per-candidate-organism
     direct-evidence screening and exclusion.
3. Build search terms from the target function card:
   - `"<enzyme name>" AND ("EC <ec>" OR "<enzyme name>" OR "<gene name>")`
   - `"<genus species>" AND ("<enzyme name>" OR "<EC number>" OR "<gene name>")`
4. Verify every returned reference before writing it anywhere. Prefer MCP
   lookup (`get_paper_by_id`, `pubmed_fetch_articles`) or user-confirmed
   records. Replace bad PMID/DOI with verified metadata; do not copy noise.
5. Classify evidence:
   - `direct_functional_evidence`: a publication directly demonstrates the
     candidate organism or candidate protein performs the target reaction.
   - `related_assay`: a paper describes a compatible assay or related enzyme
     family, useful for experimental design but not direct proof.
   - `catalytic_residue`: known active-site or mutagenesis evidence.
   - `review`: review-level context, lower priority than primary evidence.
   - `no_evidence`: no direct publication found; keep the row and mark this.
6. Write machine-readable outputs:
   - `literature_evidence.tsv`
   - optional `literature_provenance.json`
   - populated `literature_*` fields in candidate tables
   - `experimental_hypotheses.tsv` with literature citations joined after
     scoring
   - `experimental_design.md` citing only verified literature

## Output schema

`literature_evidence.tsv` columns:

- `candidate_id`
- `protein_accession`
- `organism_or_strain`
- `evidence_type`
- `reference_type` (`PMID`, `DOI`, `URL`, `manual`)
- `reference_id`
- `title`
- `first_author`
- `journal`
- `year`
- `finding`
- `verified` (`yes` / `no`)
- `source_search`
- `notes`

## Guardrails

- Do not change ranking rules because a paper exists; literature is an
  orthogonal evidence chain.
- If a candidate organism has direct and proven target function, flag it as
  `direct_literature_function` in notes and do not hide that evidence.
- If the enclosing workflow requests an excluded-taxa audit, write
  excluded-taxa evidence files exactly as the audit workflow specifies.
- When MCP tools are unavailable, say which coverage was used (OpenAlex,
  manual, or user-provided citations) and do not claim full PubMed coverage.
