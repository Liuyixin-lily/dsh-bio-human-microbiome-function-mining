# nSMase2 three-microbe demo

This is the smallest real-data demonstration for the plugin. The target is
human neutral sphingomyelinase 2 (`SMPD3_HUMAN`, nSMase2), with PDB 5UVG and
UniProt Q9NY59.

The candidate set contains three taxonomically distinct microbial proteomes on
the demonstration server:

- `Streptococcus thermophilus`
- `Staphylococcus xylosus`
- `Streptococcus pyogenes`

The server paths used by this demo are:

```text
server: 172.16.100.7
root:   /home/liuyixin/database/HSMD/plugin_demo
target: /home/liuyixin/database/HSMD/plugin_demo/inputs/SMPD3_HUMAN.faa
target: /home/liuyixin/database/HSMD/plugin_demo/inputs/SMPD3_HUMAN_5UVG.pdb
```

All candidate PDB structures are linked into `inputs/candidate_structures/`.
US-align consumes the supplied PDB structure files directly. No structure
prediction is required for the demo. DEER is the structure-based fallback only
for genomes where US-align does not leave enough suitable candidates.

Before DIAMOND, the candidate proteome FASTA is deduplicated with CD-HIT at
100% identity. This keeps the pan-proteome database non-redundant and prevents
identical proteins from the same genome or across strains from inflating the
candidate count. Set `--cluster-identity 0` on `run_diamond.py` to skip
deduplication if the input FASTA is already non-redundant.

The current demo runs the full structural pass over all 5728 precomputed
candidate PDB structures linked into `inputs/candidate_structures/`. This can
take a while. A tiny subset (`inputs/candidate_small/`) is still available if
you only need a quick end-to-end check.

To run the demo:

```bash
ssh liuyixin@172.16.100.7
cd /home/liuyixin/database/HSMD/plugin_demo
python3 human_microbiome_function_mining/scripts/example_test.py
python3 human_microbiome_function_mining/scripts/run_diamond.py \
  --query inputs/SMPD3_HUMAN.faa \
  --db inputs/candidate_proteome.faa \
  --executable /home/liuyixin/miniconda3/envs/meta/bin/diamond \
  --cdhit /home/liuyixin/miniconda3/envs/meta/bin/cd-hit \
  --cluster-identity 1.0 \
  --outdir outputs/sequence_screening
python3 human_microbiome_function_mining/scripts/run_usalign.py \
  --target inputs/SMPD3_HUMAN_5UVG.pdb \
  --candidate-dir inputs/candidate_structures \
  --executable /data/Xianjinyuan/nihaoran/enzyme_site/USalign/USalign \
  --outdir outputs/alignments/run_full_085
python3 human_microbiome_function_mining/scripts/run_deer.py \
  --project human_microbiome_function_mining/projects/nsmase2_hsmd3_demo.project.json \
  --usalign-dir outputs/alignments/run_full_085 \
  --outdir outputs/alignments/deer \
  --run
python3 human_microbiome_function_mining/scripts/merge_candidates.py \
  --sequence outputs/sequence_screening/sequence_candidates.tsv \
  --structural outputs/alignments/run_full_085/structural_candidates.tsv \
  --structural outputs/alignments/deer/Staphylococcus_xylosus/structural_candidates.tsv \
  --deer-organisms Staphylococcus_xylosus \
  --project human_microbiome_function_mining/demo/nsmase2_hsmd3.project.json \
  --output outputs/task/combined_candidates_full.tsv
python3 human_microbiome_function_mining/scripts/score_candidates.py \
  --input outputs/task/combined_candidates_full.tsv \
  --output outputs/task/scored_candidates_full.tsv \
  --target-ec 3.1.4.12
python3 human_microbiome_function_mining/scripts/extract_candidate_sequences.py \
  --candidates outputs/task/scored_candidates_full.tsv \
  --project human_microbiome_function_mining/demo/nsmase2_hsmd3.project.json \
  --outdir outputs/task/candidate_sequences
python3 human_microbiome_function_mining/scripts/summarize_candidates.py \
  --scored outputs/task/scored_candidates_full.tsv \
  --gene-evidence outputs/task/candidate_sequences/candidate_gene_evidence.tsv \
  --project human_microbiome_function_mining/demo/nsmase2_hsmd3.project.json \
  --outdir human_microbiome_function_mining/demo
```

The final ranked table is `outputs/task/scored_candidates_full.tsv`, with
`overall_rank` ordered by the explicit `priority_rule` from
`scripts/score_candidates.py`:

### Literature evidence output

`outputs/task/literature_evidence.tsv` is the demo placeholder for the
`literature-evidence` sub-skill output. It currently contains only the header,
and should be populated by the Agent after a verified literature audit of the
target enzyme and final candidates. The Agent uses the `nature-academic-search`
router when MCP literature tools are available; otherwise it gives the user
search terms or accepts `.nbib`/`.ris`/`.bib` citation files. Never fill
`literature_evidence.tsv` with unverified PMID/DOI entries.

- `USALIGN_TARGET_EC`
- `DEER_FEDKEA_CONFIRMED`
- `USALIGN_OTHER_EC`
- `USALIGN_NOT_ENZYME`
- `USALIGN_UNVALIDATED`
- `DEER_FALLBACK`
- `SEQUENCE_ONLY`
- `ANNOTATION_ONLY`

Rows carrying the same rule tie-break by `structural_score` descending, then
`sequence_score` descending, then annotation strength, then `candidate_id`
ascending. Candidates using only existing annotation remain in the source
evidence table and are merged as additional evidence, not as proof of
function.

After scoring, `extract_candidate_sequences.py` pulls the protein, CDS, and
available gene metadata for each final candidate directly from the source
genome FASTA files declared under `candidate_sequences.candidates` in the
project JSON. Outputs:

- `outputs/task/candidate_sequences/candidate_proteins.faa`
- `outputs/task/candidate_sequences/candidate_cds.ffn`
- `outputs/task/candidate_sequences/candidate_gene_evidence.tsv`
- `outputs/task/literature_evidence.tsv`
- `outputs/task/candidate_sequences/`
- `human_microbiome_function_mining/demo/high_confidence_candidate_summary.tsv`
- `human_microbiome_function_mining/demo/final_target_candidates.tsv`

`--project` on `merge_candidates.py` fills missing `organism_or_strain` and
`assembly_accession` values from the `candidate_sequences.candidates` block
when the parsed evidence table does not already carry that metadata.

On the current server dataset this demo produces no sequence candidates:
DIAMOND reports no hits for the human nSMase2 query against these three
microbial proteomes. The full US-align pass over 5,728 precomputed PDB
structures returns 4 structure-first candidates above the TM-score threshold.
Because `Staphylococcus xylosus` still lacked a suitable US-align candidate,
the DEER fallback was run only for its structure set and added the 7 best
`Staphylococcus xylosus` structure-supported candidates to the final table.
DEER evidence from the other two genomes is ignored during merging because
those genomes were already covered by US-align. The ranked list is written to
`outputs/task/scored_candidates_full.tsv`; the raw DIAMOND, US-align, and DEER
evidence are kept in `outputs/sequence_screening/` and `outputs/alignments/`
for inspection.

`Staphylococcus xylosus` is included in the US-align pass (its structure
symlinks are under `inputs/candidate_structures/`), but none of its candidate
structures reach `tm_score_mean >= 0.5`. That is why the DEER fallback was
triggered. On the demo server, DEER was configured with `deer.script_path` and
`deer.auto_run_local` using the local checkpoint under
`/home/liuyixin/00.database/deer/ckpt`; it wrote
`outputs/alignments/deer/Staphylococcus_xylosus/similarity.csv` and then
`score_candidates.py` merged the parsed DEER evidence with the US-align hits:

```bash
python3 human_microbiome_function_mining/scripts/run_deer.py \
  --project human_microbiome_function_mining/projects/nsmase2_hsmd3_demo.project.json \
  --usalign-dir /home/liuyixin/database/HSMD/plugin_demo/outputs/alignments/run_full_085 \
  --outdir /home/liuyixin/database/HSMD/plugin_demo/outputs/alignments/deer
```

If a terminal cannot access DEER, non-auto-run mode prints `REQUIRED_COMMAND`
for `Staphylococcus_xylosus` and writes
`outputs/alignments/deer/deer_trigger_summary.tsv`. After `do_retrieval.py`
finishes with `similarity.csv`, `run_deer.py` automatically calls
`parse_deer.py` and writes
`outputs/alignments/deer/Staphylococcus_xylosus/structural_candidates.tsv`.

To see the same scripts assemble a filled candidate table with synthetic rows,
run `python3 human_microbiome_function_mining/scripts/example_test.py`. The example test writes
its temporary outputs to a transient directory and verifies the parser, merge,
and scoring path without depending on DIAMOND, US-align, DEER, or FedKEA.

## Optional FedKEA validation

For the 11 final candidates, the user may validate enzyme identity and EC
number prediction with FEDKEA in either of these ways:

1. **Local install on the user's own server**: recommend this route when the
   candidate list contains 20 or more sequences. Clone
   <https://github.com/Stevenleizheng/FEDKEA>, install its dependencies, download
   the trained model, and run `main.py` on
   `outputs/task/candidate_sequences/candidate_proteins.faa`. The exact commands
   are documented in `references/README.md`. This is suitable when the user has
   their own compute or wants to keep data on their own server.
2. **Manual web submission**: recommend this route when the candidate list has
   fewer than 20 sequences. Submit the candidate protein sequences to the
   FedKEA web server, save the returned
   `binary_result.txt`, `enzyme_result_with_probability.csv`, and
   `enzyme_result_with_confidence.csv` files, then provide them to the Agent or
   run `scripts/parse_fedkea.py` locally.

The current demo has 11 extracted candidates, which is below the 20-candidate
threshold, so the web version is a reasonable route for the 7 DEER-only
candidates from `Staphylococcus xylosus`. In this demo run we used a mixed
route:

1. The 4 US-align candidates were validated with a local FedKEA install on the
   demo server at `/home/liuyixin/00.database/FEDKEA` and written under
   `outputs/fedkea/local_result/`.
2. The 7 `Staphylococcus xylosus` DEER candidates were submitted manually to
   the FedKEA web version, and the returned result table was pasted back into
   `outputs/fedkea/fedkea_web_result_*` / `fedkea_results.tsv` for merging.

The Agent can also call `scripts/run_fedkea.py` when the configured local
FEDKEA `main.py` is accessible from the current terminal and `auto_run_local`
is enabled. It never calls the FedKEA web server programmatically; it only
consumes saved result files.

FedKEA should normally receive the final candidate protein subset
(`outputs/task/candidate_sequences/candidate_proteins.faa` or an equivalent
candidate FASTA), not the full proteome. Candidate headers keep the accession
as the first field, and parse/run calls should include `--expected-accessions`
(for example, a list of the submitted candidate IDs) so output accessions are
checked before FedKEA evidence is merged.

For this demo, the four `Staphylococcus xylosus` DEER hits that FedKEA
classified as non-enzymes (from the manually submitted web batch) are:

- `WP_340083110.1`: `IsEnzyme=No`, probability 0.015951
- `WP_029377471.1`: `IsEnzyme=No`, probability 0.000067
- `WP_340083393.1`: `IsEnzyme=No`, probability 0.000335
- `WP_029379012.1`: `IsEnzyme=No`, probability 0.000642

The three `Staphylococcus xylosus` DEER hits that FedKEA confirmed as enzymes
have predicted EC numbers outside `3.1.4.12`:

- `WP_326009104.1`: `IsEnzyme=Yes`, probability 0.999771, predicted `5.3.1.4`
  (L-arabinose isomerase)
- `WP_340082858.1`: `IsEnzyme=Yes`, probability 0.999748, predicted `3.1.11.6`
  (exodeoxyribonuclease VII)
- `WP_038679090.1`: `IsEnzyme=Yes`, probability 0.943296, predicted `3.4.22.15`
  (cathepsin L)

The four US-align hits were all confirmed as enzymes by FedKEA:

- `WP_023610742.1`: `3.1.4.12`, sphingomyelin phosphodiesterase, High
- `1111525849483863_bin.19_00773`: `3.1.4.12`, sphingomyelin phosphodiesterase,
  High
- `1111525849483863_bin.19_01722`: `3.1.11.2`, exodeoxyribonuclease III, High
- `WP_023610361.1`: `3.1.11.2`, exodeoxyribonuclease III, High

The 4 US-align hits included two target nSMase candidates and two
exodeoxyribonuclease III candidates; only the two nSMase candidates match the
target function EC `3.1.4.12`. In the final explicit ranking, the three
`Staphylococcus xylosus` DEER hits that FedKEA confirmed as enzymes are sorted
above the two US-align hits with a non-target EC (`USALIGN_OTHER_EC`), but they
are still not target nSMase candidates because their predicted ECs remain
outside `3.1.4.12`. The wet-lab validation therefore focuses on the two
`USALIGN_TARGET_EC` candidates:

- `WP_023610742.1` (`Streptococcus pyogenes`)
- `1111525849483863_bin.19_00773` (`Streptococcus thermophilus`)

The final high-confidence nSMase hit list remains the same two candidates:

- `WP_023610742.1` (`Streptococcus pyogenes`)
- `1111525849483863_bin.19_00773` (`Streptococcus thermophilus`)

The full validation results, when the user runs FedKEA, are written under
`outputs/fedkea/fedkea_results.tsv`; the refined verdicts are in
`demo/high_confidence_candidate_summary.tsv`.

## Final candidate experimental design

For the two high-confidence nSMase candidates, a wet-lab validation plan is
provided as:

- `demo/final_target_candidates.tsv`: final two-row candidate table with
  US-align structural evidence, FedKEA EC prediction, source annotation, gene
  locus/location, and source FASTA paths.
- `demo/experimental_design.md`: generic entry point that points to the full
  experimental plan and required controls.
