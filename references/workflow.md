# Target workflow

Follow the functional discovery workflow when this plugin is used.
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
skip this preparation step when gene nucleotide output is not requested. When
the final deliverables must include gene sequences, also require per-genome
`.fna` genomic FASTA input or download it through `genome-download`.

```text
User input
    -> target function card
    -> reference enzyme set
    -> sequence screening
    -> existing source-file annotation capture (.faa/.gbff annotations)
    -> branch:
       if sequence hit AND existing annotation match the target function:
         mark SEQUENCE_ANNOTATION_CONFIRMED and skip structure steps
       else:
         -> check candidate structure files (PDB/CIF)
         -> if structures missing, run bundled structure-prediction sub-skill
         -> US-align all available candidate structures
         -> DEER fallback when a genome has no US-align candidate or lacks enough of them,
            and also when the merged candidate list has no qualifying candidate at all
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

Existing source-file annotations are a lightweight evidence chain when used
alone. However, when a DIAMOND sequence hit and the existing `.faa`/`.gbff`
annotation both match the target function (same target EC, enzyme name, or a
direct reaction-product synonym), take the sequence+annotation fast path: mark
the row `SEQUENCE_ANNOTATION_CONFIRMED` and skip structure-prediction,
US-align, DEER, and catalytic-pocket mapping. Structure screening is only
required when sequence+annotation evidence is absent, ambiguous, unknown, or
contradicts the target. If DIAMOND has no sequence hit at all, the workflow must
not stop: continue to structure screening and FedKEA so that structural and
functional evidence can still be collected. An existing `.faa`/`.gbff` annotation
such as `sph` is additional evidence in that case, but it is not equivalent to a
DIAMOND sequence hit and does not by itself create a
`SEQUENCE_ANNOTATION_CONFIRMED` row.

Existing annotation fields can add protein/gene names, EC numbers,
Pfam/InterPro/TIGRFAM/CAZy/KEGG/COG/GO identifiers, and product descriptions
already present in the user's `.faa`/`.gbff` inputs, and they remain useful for
FedKEA comparison, literature alignment, and hypothesis generation.

## FedKEA validation scope

- FedKEA is an orthogonal functional validation layer after sequence and
  structure screening have produced a candidate subset.
- **Input scope**: by default, run FedKEA only on the candidate protein FASTA
  produced by `scripts/extract_candidate_sequences.py`
  (`candidate_proteins.faa`) or an equivalent candidate subset derived from
  `structural_candidates.tsv`, not on the full genome proteome. Running on the
  entire proteome is allowed only when the user explicitly asks for a
  whole-proteome enzyme scan.
- **FASTA header rule**: candidate FASTA headers must place the accession as
  the first whitespace-delimited field with no description (for example
  `>WP_000000000.1`). When FedKEA receives a multi-word header, its output
  accession can collapse to `MULTISPECIES:` or another truncated token and
  cannot be joined back to the candidate IDs.
- **Accession check**: pass `--expected-accessions` to `scripts/parse_fedkea.py`
  or set `validation_inputs.fedkea.expected_accessions` in `project.json` so
  the parser verifies that FedKEA output accessions can be joined to the
  expected candidate subset. Zero overlap is a hard failure; partial mismatch
  is recorded in `fedkea_notes`.
- Keep the original FedKEA file paths and tool version in `fedkea_results.tsv`
  and `combined_candidates.tsv` so every validation field is traceable.


## 序列证据链（快速通道）/ the sequence evidence chain

快速通道不是"有一条命中"就算，它要求三件事同时成立，并且都写进表里：

1. **参照物**：`representative_id` —— 命中的是哪条模板酶（DIAMOND `qseqid`）。没有它，两行
   40% identity 到不同酶的命中看起来是同一类证据。
2. **比对强度**：`pident` / `query_coverage` / `evalue`，随候选一起进入 scored 与 final 表。
3. **候选自己的注释**：来自基因组的 GenBank/GFF（`merge_source_annotations.py` 并入），
   与目标活性方向一致才算 `SEQUENCE_ANNOTATION_CONFIRMED`。

粒度约定：`sequence_hits.tsv` 保留每一条 (模板, 候选) 对齐；`sequence_candidates.tsv` 与
`final_target_candidates.tsv` 每个蛋白一行（取最佳比对），所以"候选数"不等于"对齐数"。

**已知限制**：模板集可能包含与目标同种的条目（如 *S. epidermidis* 自己的 reviewed ADH）。
这时 100% identity 是同种自比对，不是跨物种的功能证据；当前表能看出模板 accession，但还不能
自动标记 `same_species`。看到 100% 命中时先核对模板物种。
