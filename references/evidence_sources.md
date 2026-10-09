# Existing evidence sources

This repository already contains files that can feed the plugin:

- `data/target_enzymes/*.faa`: target enzyme protein sequences.
- `data/target_structures/*.pdb`: target structures.
- `data/target_enzymes/*_active_site_residues.tsv`: active site and catalytic pocket residues.
- `data/manual_proteomes/*.faa`: small local candidate proteomes for demonstrations.
- When users supply their own `.faa` or `.gbff` files, those files may already
  contain protein annotations. The plugin should parse and preserve that
  existing-knowledge evidence before replacing it with screening evidence.
- `data/enzyme_registry.tsv` and `data/target_enzymes.example.tsv`: enzyme metadata.
- `data/skin_taxa_registry*.tsv`: candidate taxon registries.
- `data/gcf_accessions*.tsv`: genome accession lists.
- `results/*.tsv`: rankings and evidence tables from previous runs.
- `scripts/`: reusable deterministic steps.

If the user starts from taxa/accession/source metadata instead of an existing
candidate proteome, use `references/genome_dataset_preparation.md` first.
That flow calls the bundled `genome-search`, `genome-download`, and
`genome-annotation` sub-skills and writes prepared genomes under
`databases/genomes/<species>/`.

When a user supplies their own dataset, they should replace these paths in their
`project.json` without changing the plugin protocol.
