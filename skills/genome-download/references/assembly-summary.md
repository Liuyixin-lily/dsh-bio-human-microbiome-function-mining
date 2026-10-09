# NCBI Assembly Summary Notes

The NCBI FTP tree keeps `assembly_summary.txt` files under group directories:

```text
https://ftp.ncbi.nlm.nih.gov/genomes/refseq/bacteria/assembly_summary.txt
https://ftp.ncbi.nlm.nih.gov/genomes/refseq/{group}/assembly_summary.txt
https://ftp.ncbi.nlm.nih.gov/genomes/genbank/{group}/assembly_summary.txt
```

The table is tab-delimited. The first column is the RefSeq/GCF accession (or GenBank/GCA accession) and the last column is the FTP path used as the base for genome files. Example `ftp_path`:

```text
ftp://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/025/143/015/GCF_025143015.1_ASM2514301v1
```

The `https` equivalent used by this skill is:

```text
https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/025/143/015/GCF_025143015.1_ASM2514301v1
```

NCBI genome folders contain assembly basenames such as `GCF_..._genomic.fna.gz`, `GCA_..._protein.faa.gz`, `*_cds_from_genomic.fna.gz`, `*_genomic.gbff.gz`, and `*_genomic.gff.gz`. Notice the underscore before the file type; older URL builders that used a dot (`*_ASMv1.genomic.fna.gz`) will 404 against current NCBI layouts.

## Assembly source

Select the summary by accession prefix:

```text
GCF -> refseq
GCA -> genbank
```

For a mixed GCF/GCA list, load the RefSeq and GenBank summaries and match each accession against the appropriate table.

## Picking the right group

The initial summary should match the taxon group. For bacteria:

```text
https://ftp.ncbi.nlm.nih.gov/genomes/refseq/bacteria/assembly_summary.txt
```

For non-bacterial species, use the matching group under `https://ftp.ncbi.nlm.nih.gov/genomes/refseq/{group}/assembly_summary.txt`. Known groups include:

```text
bacteria
archaea
fungi
protozoa
viral
plant
vertebrate_mammalian
vertebrate_other
invertebrate
```

If an accession is reported as missing from the summary, do not assume the assembly is unavailable; first map the species to its biological group and retry with that group's summary. Some assemblies are also present in GenBank (`GCA`) but not yet in RefSeq (`GCF`).

## Complete-file preflight

The default standard file set is:

```text
*_genomic.fna.gz
*_protein.faa.gz
*_cds_from_genomic.fna.gz
*_genomic.gbff.gz
*_genomic.gff.gz
```

`build_download_links.py` preflights these files with HTTP HEAD requests before downloading. If any requested file is unavailable, the whole accession is skipped and recorded in `download_skipped_accessions.txt`. This prevents partial species folders and downstream assembly mismatches.

## Species folder naming

When the metadata includes human-readable species names, create one folder per species using underscored names. Replace spaces and `/` with `_` so paths remain shell-friendly, for example `Acinetobacter calcoaceticus` becomes `Acinetobacter_calcoaceticus`.

## Decompression after download

NCBI serves the standard genome files in gzip format. The skill's `download_genomes.py` uses gzip-magic validation while downloading and supports `--decompress`, which unpacks each validated `.gz` file into the same species folder and removes the archive. This is useful when the downstream pipeline expects plain FASTA, GFF, GBFF, or protein FASTA files.

When `--decompress` is used, `*_cds_from_genomic.fna` files are renamed to `*_genomic.ffn` after unpacking. This matches the conventional nucleotide FASTA suffix used by many gene/protein prediction workflows. The original `_cds_from_genomic.fna` name should not remain in the output folder.
