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

**Tool boundary**: the plugin does not bundle a literature search engine. It
delegates to the external `nature-academic-search` skill. A working bridge is
shipped at `scripts/run_literature_search.sh`, which locates that skill and a
Python >= 3.10 automatically:

```bash
# 0. confirm the route is live (do this first; if it fails, see the wrapper's
#    error message for remedies)
bash scripts/run_literature_search.sh --check

# 1. search -> resolve to verified PMIDs WITH ABSTRACTS
bash scripts/run_literature_search.sh "sphingomyelinase Staphylococcus epidermidis" \
  --limit 10 --resolve

# 2. or resolve a specific known DOI
bash scripts/run_literature_search.sh --doi 10.1016/j.chom.2022.01.004
```

If MCP literature tools are unavailable and the wrapper cannot run, fall back to
the skill's OpenAlex-limited search or give the user exact PubMed / Google
Scholar search terms and wait for returned citations. Never fabricate PMID, DOI,
title, journal, year, or finding.

**MANDATORY triage rule**: never classify a hit as `no_evidence` or irrelevant
from its **title** alone. Read the abstract (`--resolve` fetches it). A decisive
paper can be missed this way - e.g. "*Commensal Staphylococcus epidermidis
contributes to skin barrier homeostasis by generating protective ceramides*"
(PMID 35123653) does not contain the word "sphingomyelinase" in its title but
directly proves the sphingomyelinase reaction. Before writing any `no_evidence`
row, confirm that you used at least these three query shapes:

1. `"<enzyme name>" AND "<genus species>"`
2. `"<genus species>" AND (<product> OR <pathway> OR <phenotype>)` - i.e. search
   by the **biological outcome**, not only the enzyme name
3. `"<gene name>" AND "<genus species>"` - gene symbols (`sph`, `hlb`, ...) often
   carry the literature when the enzyme name does not

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
2. Run the search through the bundled bridge (see Tool boundary above):
   `bash scripts/run_literature_search.sh "<query>" --limit 10 --resolve`.
   Follow `nature-academic-search` workflow routing underneath:
   - Use `multi-source-search` for enzyme/method papers.
   - Use `candidate-evidence-audit` when the user needs per-candidate-organism
     direct-evidence screening and exclusion.
   **Read every returned abstract before classifying it.**
3. Build search terms from the target function card. Cover all three shapes:
   - `"<enzyme name>" AND ("EC <ec>" OR "<enzyme name>" OR "<gene name>")`
   - `"<genus species>" AND ("<enzyme name>" OR "<EC number>" OR "<gene name>")`
   - `"<genus species>" AND (<expected product> OR <pathway> OR <phenotype>)`

   **Record the exact queries used** in the `source_search` column, so an empty
   result is auditable rather than an assertion.
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
- **Never write a `no_evidence` row from titles alone.** Read abstracts, and
  record the queries and coverage that justify the negative claim. A
  `no_evidence` verdict that comes from an under-specified search is a
  fabrication-adjacent error: it asserts absence without evidence of searching.
- If a `no_evidence` row is later contradicted, correct the row and note the
  correction instead of silently deleting it.
