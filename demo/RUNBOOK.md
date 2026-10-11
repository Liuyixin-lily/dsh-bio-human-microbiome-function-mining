# nSMase2 three-microbe demo runbook

This runbook is a clean command sequence for reproducing the real-data demo on
the demonstration server. It assumes the plugin tree is already present at
`/home/liuyixin/database/HSMD/plugin_demo/human_microbiome_function_mining/`.

Server details:

```text
server: 172.16.100.7
user:   liuyixin
root:   /home/liuyixin/database/HSMD/plugin_demo
target: human neutral sphingomyelinase 2 (nSMase2, SMPD3, EC 3.1.4.12)
```

## 1. Enter the demo root

```bash
ssh liuyixin@172.16.100.7
cd /home/liuyixin/database/HSMD/plugin_demo
```

## 2. Verify inputs

```bash
ls -la inputs/SMPD3_HUMAN.faa \
  inputs/SMPD3_HUMAN_5UVG.pdb \
  inputs/candidate_proteome.faa
find inputs/candidate_structures -name '*.pdb' | wc -l
```

The expected candidate structure count is 5728.

## 3. Optionally run the synthetic example test

```bash
python3 human_microbiome_function_mining/scripts/example_test.py
```

This verifies parsing/merging/ranking without external tools.

## 4. Fetch the reference enzyme set automatically

The plugin can build the reference enzyme set from public NCBI and RCSB PDB
endpoints instead of requiring the user to upload a TSV. The demo project
already configures `reference_enzyme` in
`human_microbiome_function_mining/projects/nsmase2_hsmd3_demo.project.json`, so this step can
run with no additional arguments:

```bash
cd /home/liuyixin/database/HSMD/plugin_demo
python3 human_microbiome_function_mining/scripts/fetch_reference_enzymes.py \
  --project human_microbiome_function_mining/projects/nsmase2_hsmd3_demo.project.json
```

This writes:

- `outputs/task/reference_enzyme_set.tsv` (the reference enzyme contract table)
- `outputs/task/reference_enzymes.faa` (reference sequences, when fetched)
- `outputs/task/reference_provenance.json` (source URLs and query provenance)

The reference FASTA can be used as the upstream reference enzyme set for
sequence screening, and the TSV remains available for evidence-chain review.
The demo project JSON lives under `human_microbiome_function_mining/projects/`; if you copy a
project file into the demo root instead, update the path above.

## 5. Run DIAMOND sequence screening (with CD-HIT 100% deduplication)

```bash
python3 human_microbiome_function_mining/scripts/run_diamond.py \
  --query inputs/SMPD3_HUMAN.faa \
  --db inputs/candidate_proteome.faa \
  --executable /home/liuyixin/miniconda3/envs/meta/bin/diamond \
  --cdhit /home/liuyixin/miniconda3/envs/meta/bin/cd-hit \
  --cluster-identity 1.0 \
  --identity 20.0 \
  --coverage 0.7 \
  --outdir outputs/sequence_screening
```

DIAMOND may report zero sequence candidates for this target/pan-proteome pair.
That is the expected behavior for the demo.

## 6. Run full US-align structural screening

```bash
python3 human_microbiome_function_mining/scripts/run_usalign.py \
  --target inputs/SMPD3_HUMAN_5UVG.pdb \
  --candidate-dir inputs/candidate_structures \
  --executable /data/Xianjinyuan/nihaoran/enzyme_site/USalign/USalign \
  --outdir outputs/alignments/run_full_085
```

This loops over all candidate PDB structures. On the demo server it writes
`outputs/alignments/run_full_085/usalign_stdout.txt` and the parsed
`structural_candidates.tsv`.

If the full US-align output has already been parsed, this step does not need to
be repeated. The demo server already has complete output under
`outputs/alignments/run_full_085/`. DEER is a fallback and should only be run
for genomes where US-align does not leave enough suitable candidates. In this
demo, only `Staphylococcus_xylosus` triggers DEER; do not run DEER needlessly
for the other two genomes.

## 7. Merge evidence

```bash
python3 human_microbiome_function_mining/scripts/merge_candidates.py \
  --structural outputs/alignments/run_full_085/structural_candidates.tsv \
  --structural outputs/alignments/deer/Staphylococcus_xylosus/structural_candidates.tsv \
  --deer-organisms Staphylococcus_xylosus \
  --project human_microbiome_function_mining/demo/nsmase2_hsmd3.project.json \
  --output outputs/task/combined_candidates_full.tsv
```

Include `--sequence <sequence_candidates.tsv>` only when DIAMOND produced
sequence candidates. In the demo, DIAMOND finds zero hits for this target and
pan-proteome pair, so no sequence table is passed.

## 8. Score

```bash
python3 human_microbiome_function_mining/scripts/score_candidates.py \
  --input outputs/task/combined_candidates_full.tsv \
  --output outputs/task/scored_candidates_full.tsv \
  --target-ec 3.1.4.12
```

Expected demo output: 11 candidates after the DEER fallback (`4 US-align
candidates + 20 DEER hits for Staphylococcus xylosus`, with 11 unique
accessions passing merge), ranked with
explicit `priority_rule` tiers from `scripts/score_candidates.py`
(US-align target-EC first, then DEER confirmed by FedKEA, then US-align
other-EC, then remaining DEER fallback).

## 9. Extract final candidate sequences

```bash
python3 human_microbiome_function_mining/scripts/extract_candidate_sequences.py \
  --candidates outputs/task/scored_candidates_full.tsv \
  --project human_microbiome_function_mining/demo/nsmase2_hsmd3.project.json \
  --outdir outputs/task/candidate_sequences
```

Outputs:

- `outputs/task/candidate_sequences/candidate_proteins.faa`
- `outputs/task/candidate_sequences/candidate_cds.ffn`
- `outputs/task/candidate_sequences/candidate_gene_evidence.tsv`

Then generate the compact summary and final target tables:

```bash
python3 human_microbiome_function_mining/scripts/summarize_candidates.py \
  --scored outputs/task/scored_candidates_full.tsv \
  --gene-evidence outputs/task/candidate_sequences/candidate_gene_evidence.tsv \
  --project human_microbiome_function_mining/demo/nsmase2_hsmd3.project.json \
  --outdir human_microbiome_function_mining/demo
```

## 11. Merge optional FedKEA web result

If the user obtained a FedKEA result from the web server, recommend the web
version when there are fewer than 20 candidate sequences; recommend the local
FEDKEA software run when there are 20 or more.

For this demo, the 4 US-align candidates were validated with the local FedKEA
runtime under `/home/liuyixin/00.database/FEDKEA`; the returned files from that
local run were parsed into `outputs/fedkea/fedkea_results.tsv`. Save or copy
the equivalent returned files
`binary_result.txt`, `enzyme_result_with_probability.csv`, and
`enzyme_result_with_confidence.csv` under `outputs/fedkea/result/`, then parse:

```bash
python3 human_microbiome_function_mining/scripts/parse_fedkea.py \
  --confidence-csv outputs/fedkea/result/enzyme_result_with_confidence.csv \
  --expected-accessions outputs/alignments/run_full_085/structural_candidates.tsv \
  --output outputs/fedkea/fedkea_results.tsv \
  --tool-version "FedKEA local result"
```

`--expected-accessions` makes the parser verify that FedKEA output accessions
can be joined back to the candidate subset that was actually submitted. If a
run covers candidates from more than one structural table, pass a single list
or generated TSV containing every submitted candidate accession.

For a manually downloaded web result, either paste the table into the same
contract TSV format or append the returned rows to
`outputs/fedkea/fedkea_results.tsv`. In this demo the 7 `Staphylococcus
xylosus` DEER candidates were submitted manually to the FedKEA web version and
their returned rows were pasted into this table.

Then merge and score with the complete FedKEA evidence:

```bash
python3 human_microbiome_function_mining/scripts/merge_candidates.py \
  --structural outputs/alignments/run_full_085/structural_candidates.tsv \
  --structural outputs/alignments/deer/Staphylococcus_xylosus/structural_candidates.tsv \
  --deer-organisms Staphylococcus_xylosus \
  --project human_microbiome_function_mining/demo/nsmase2_hsmd3.project.json \
  --fedkea outputs/fedkea/fedkea_results.tsv \
  --output outputs/task/combined_candidates_full.tsv

python3 human_microbiome_function_mining/scripts/score_candidates.py \
  --input outputs/task/combined_candidates_full.tsv \
  --output outputs/task/scored_candidates_full.tsv \
  --target-ec 3.1.4.12
```

## Final artifacts

- `outputs/task/scored_candidates_full.tsv`
- `outputs/task/combined_candidates_full.tsv`
- `outputs/task/candidate_sequences/candidate_proteins.faa`
- `outputs/task/candidate_sequences/candidate_cds.ffn`
- `outputs/task/candidate_sequences/candidate_gene_evidence.tsv`
- `outputs/task/literature_evidence.tsv`
- `outputs/fedkea/fedkea_results.tsv`
- `human_microbiome_function_mining/demo/high_confidence_candidate_summary.tsv`
- `human_microbiome_function_mining/demo/final_target_candidates.tsv`

The final ranked table includes `fedkea_*` fields when FedKEA results are
provided. After this merge, all 11 demo candidates should have FedKEA evidence
(4 from the first US-align round, 7 from the Staphylococcus xylosus DEER round).

`outputs/task/literature_evidence.tsv` is the placeholder file for the
`literature-evidence` sub-skill. It currently has only the schema header and is
meant to receive verified PMID/DOI rows from a literature audit. Use the
`nature-academic-search` router when MCP literature tools are available;
otherwise provide exact search terms or accept user-returned `.nbib`/`.ris`/
`.bib` files. Do not fill this file with unverified references.
