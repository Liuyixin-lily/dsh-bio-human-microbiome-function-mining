# Target workflow

Follow the functional dark matter discovery workflow when this plugin is used.
Heavy tools run when their executables and inputs are accessible from the
current terminal; otherwise the user's runner or the user runs them.

Optional dataset preparation entry:

```text
taxa / source metadata / GCF/GCA accessions
    -> genome-search (select matching NCBI assemblies)
    -> genome-download (download genomic.fna, protein.faa, genomic.gbff, ...)
    -> genome-annotation (Bakta if needed)
    -> candidate proteome for sequence screening
```

If the user already has a candidate proteome `.faa` and/or annotated `.gbff`,
skip this preparation step.

```text
User input
    -> target function card
    -> reference enzyme set
    -> sequence screening
    -> existing source-file annotation capture (.faa/.gbff annotations)
    -> check candidate structure files (PDB/CIF)
    -> if structures missing, run bundled structure-prediction sub-skill
    -> US-align all available candidate structures
    -> DEER fallback only when a genome lacks enough US-align candidates
    -> catalytic residue / pocket analysis
    -> genome context
    -> ecological evidence
    -> candidate scoring
    -> falsifiable experimental hypotheses
    -> experimental design
```

Do not run US-align until the candidate structure files are materialized. If a
candidate lacks a structure, run the bundled `structure-prediction` sub-skill
with priority: experimental PDB > AlphaFold DB model passing
`mean pLDDT >= 60` > homology model > de novo prediction, then continue when
the returned files are available. Use DEER only as a fallback after US-align has
been attempted and a genome still has insufficient candidates.

Each step should consume files from the user's existing project when available.
If an intermediate table does not exist, the workflow should ask for it or mark
the step pending instead of inventing output.

Before `makedb`, deduplicate the candidate proteome with CD-HIT. Use 100%
identity when each organism has a single genome; use 95% for multi-genome
pan-proteomes unless the user overrides it in `project.json` or with
`--cluster-identity`.

Existing source-file annotations are a lightweight evidence chain, not a
substitute for sequence or structure screening. They can add protein/gene
names, EC numbers, Pfam/InterPro/TIGRFAM/CAZy/KEGG/COG/GO identifiers, and
product descriptions already present in the user's `.faa`/`.gbff` inputs.
