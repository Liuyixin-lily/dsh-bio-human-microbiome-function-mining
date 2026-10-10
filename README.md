# Human Microbiome Function Mining Plugin

人体微生物组功能挖掘插件 / DeepSeek Harness plugin for discovering candidate proteins with a target enzyme function from human-associated microbial genomes. English: [README.en.md](README.en.md)

`human-microbiome-function-mining` 是一个可安装到 DeepSeek Harness（dsh）或兼容 Agent harness 的插件交付包。它把目标酶输入标准化、候选基因组准备、CD-HIT 去冗余、DIAMOND 序列筛选、US-align 结构证据、DEER fallback、FedKEA 酶功能/EC 预测、已有注释证据合并、文献证据审计、可证伪实验假设生成和实验设计组织成可复用流程。

This is a DeepSeek harness plugin: users install or load the package into their harness, then the Agent can use the bundled skills, scripts, schemas, and reference rules. The plugin does not host services, does not package external bioinformatics tools, and does not provide compute.

初次使用请先看 [QUICKSTART.md](QUICKSTART.md)，它说明如何安装/载入插件、如何跑内置自测，以及如何改成用户自己的数据；英文版见 [README.en.md](README.en.md)。

---

## What it is / 这个插件是什么

- Turns a target enzyme sequence, EC number, or substrate-product reaction into candidate microbial proteins.
- Standardizes the target into a `target_function_card.json`.
- Organizes sequence screening, structure screening, functional/EC validation, literature evidence, and final ranking.
- Executes external tools only when the user provides accessible executable and data paths and allows the Agent to run them locally. Otherwise it writes exact commands and consumes returned outputs.

- 输入目标酶、EC 号或底物-产物关系，输出候选蛋白证据表、排序表和实验设计。
- 插件提供技能、脚本、schema 与资料，不替代 DIAMOND、CD-HIT、US-align、DEER、FedKEA、Bakta 或文献数据库。
- 外部工具是否由 Agent 直接执行，由“路径是否可访问 + 用户是否允许”决定。

---

## Directory layout / 目录结构

```text
human_microbiome_function_mining/
├── package.json                 # dsh npm package manifest
├── index.js                     # ESM entry
├── cordis.patch.yml             # dsh bundle patch: plugin row + preset declaration
├── src/                         # dsh runtime registration (skills + system prompt)
├── preset/                      # dsh agent preset (persona + preset skills)
├── agents/deepseek.md           # DeepSeek agent prompt and execution guardrails
├── config.minimal.example.json  # lean example configuration
├── config.example.json          # fuller project/tool configuration reference
├── LICENSE                      # MIT license
├── SKILL-PROVENANCE.yaml        # skill adaptation ledger
├── references/                  # workflow, thresholds, fallback and evidence rules
├── schemas/                     # machine-readable evidence-table contracts
├── scripts/                     # parsers, wrappers, ranking, and example test
├── projects/                    # example project configuration files
└── skills/                      # main skill plus independent sub-skills
```

---

## Skills / 技能

- `functional-dark-matter-discover`: 主流程，负责把目标酶/EC/反应变成候选与实验设计。
- `build-target-function-card`: 标准化目标输入，生成 Target Function Card。
- `screen-sequence-candidates`: 运行或消费 DIAMOND 序列筛选，默认先做 CD-HIT 去冗余；单菌单基因组默认 100%，多基因组泛蛋白组默认 95%。
- `structure-prediction`: 当候选蛋白没有已知结构文件时，按 PDB > AlphaFold DB（mean pLDDT >= 60）> homology model > de novo prediction 的优先级检索或预测结构；内置的 PDB/AFDB/homology 辅助脚本在 `skills/structure-prediction/scripts/` 中，为 US-align 准备 `structure/<protein_sequence_id>.pdb`。
- `screen-structure-candidates`: 结构证据筛选。先检查候选结构文件是否存在；没有结构文件时先运行内置 `structure-prediction` 子 skill 获取候选结构，再对全部候选结构直接 US-align；只有某个基因组 US-align 候选不足时才按用户同意跑 DEER fallback。
- `literature-evidence`: 文献证据审计。可用 MCP 文献工具时走 `nature-academic-search` 类流程，否则给出检索词或接收用户提供的已验证引用文件；禁止编造 PMID/DOI。
- `genome-search`: 从 NCBI Assembly/BioSample 元数据中选择候选 GCF/GCA。
- `genome-download`: 批量下载 RefSeq/GCF 或 GenBank/GCA 基因组文件。
- `genome-annotation`: 用 Bakta 给新下载基因组建库并注释。

The three genome sub-skills are independent deliverables. Load them when users have taxa or accession lists but do not already have a candidate proteome `.faa` or annotated `.gbff` dataset.

---

## Core workflow / 核心流程

```text
target enzyme / EC / substrate-product
  -> target_function_card.json
  -> preflight check .faa/.ffn/.gbff and structure paths
  -> optional genome-search / genome-download / genome-annotation
  -> CD-HIT deduplication (100% for single-genome datasets; 95% for multi-genome pan-proteomes)
  -> DIAMOND sequence screening
  -> parse existing .faa/.gbff annotations
  -> check candidate structure files (PDB/CIF)
  -> if structures missing, run bundled structure-prediction sub-skill
  -> direct US-align against the reference target structure for all available candidate structures
  -> DEER only as fallback for genomes without enough US-align candidates
  -> optional catalytic-pocket, genome-context, and ecological evidence
  -> optional FedKEA enzyme/EC evidence
  -> literature-evidence audit (verified PMID/DOI evidence)
  -> merge combined_candidates.tsv
  -> structure-first candidate ranking
  -> falsifiable experimental hypotheses
  -> experimental design
```

默认排序是“结构证据优先、序列证据次之”，由 `scripts/score_candidates.py` 给出确定性的 `overall_rank`。脚本内部按优先级排序，再按结构分、序列分、注释强度、`candidate_id` 破平。`priority_rule`、`priority_order` 只作为可选溯源列保留，最终对外交付表以 `overall_rank` 为准。

The final ranked table is `scored_candidates_full.tsv`, with `overall_rank` as the explicit deliverable ranking field. Optional `priority_rule` / `priority_order` columns may be present for traceability but are not required by the schema.

Priority policy used by `score_candidates.py`:

1. `USALIGN_TARGET_EC`
2. `DEER_FEDKEA_CONFIRMED`
3. `USALIGN_OTHER_EC`
4. `USALIGN_NOT_ENZYME`
5. `USALIGN_UNVALIDATED`
6. `DEER_FALLBACK`
7. `SEQUENCE_ONLY`
8. `ANNOTATION_ONLY`

---

## Tool execution boundary / 工具执行边界

The plugin does not silently download or install DIAMOND, CD-HIT, US-align, DEER, FedKEA, or Bakta.

1. Read executable and data paths from `project.json` / config example, or ask the user.
2. Check whether the executable and required inputs are accessible from the current terminal.
3. If accessible and `auto_run_local` is enabled, run the configured command and parse the output.
4. If not accessible, or the user does not want direct execution, write a pending checkpoint with the exact command and consume returned files.
5. Never invent tool output. Never call the FedKEA web server programmatically.

For structure evidence, first check whether candidate structure files (PDB/CIF)
exist. If a candidate lacks a structure, run the bundled `structure-prediction`
sub-skill (experimental PDB > AlphaFold DB model passing `mean pLDDT >= 60` >
homology model > de novo) and continue only after the returned structures are
materialized as `structure/<protein_sequence_id>.pdb`. Then use US-align on all
available candidate structure files. Use DEER only for a genome when US-align
does not produce enough suitable candidates for that genome and the user agrees.

---

## Installation / 安装

DeepSeek Harness npm/bundle form:

```bash
# Local directory
npx -y @deepseek-ai/dsh plugin --profile web add ./human_microbiome_function_mining

# Tarball built from this repository
npx -y @deepseek-ai/dsh plugin --profile web add ./human_microbiome_function_mining.tar.gz

# Once published/mirrored
npx -y @deepseek-ai/dsh plugin --profile web add @dsh-bio/human-microbiome-function-mining
npx -y @deepseek-ai/dsh plugin --profile web add github:Liuyixin-lily/dsh-bio-human-microbiome-function-mining
```

The `postinstall` script installs the agent preset into
`~/.dsh/.agent-presets/human-microbiome-function-mining`.

---

## Quick start / 快速开始

```bash
cp human_microbiome_function_mining/config.minimal.example.json project.json
```

Edit `project.json` input and tool paths:

- `inputs.target_sequence_fasta`
- `reference_enzyme.enzyme_name` / `ec` (fetched automatically when network is available)
- `inputs.candidate_proteome_fasta`
- `inputs.target_structure_pdb`
- DIAMOND/CD-HIT executable paths
- candidate PDB/CIF structure directory
- US-align executable
- optional DEER `do_retrieval.py` and its `ckpt_dir`
- optional Bakta database and environment
- optional local FedKEA `main.py`

Sanity check without external tools:

```bash
cd human_microbiome_function_mining
python3 scripts/preflight_inputs.py --project project.json
python3 scripts/example_test.py
# example test passed
```

Typical wrapper entry points:

```bash
python3 human_microbiome_function_mining/scripts/fetch_reference_enzymes.py --project project.json
python3 human_microbiome_function_mining/scripts/preflight_inputs.py --project project.json
python3 human_microbiome_function_mining/scripts/run_diamond.py --project project.json
python3 human_microbiome_function_mining/scripts/run_usalign.py --project project.json
python3 human_microbiome_function_mining/scripts/run_deer.py --project project.json
python3 human_microbiome_function_mining/scripts/run_bakta.py --project project.json
python3 human_microbiome_function_mining/scripts/run_fedkea.py --project project.json
```

External tool sources:

```text
DEER    https://github.com/WangJiuming/deer
FedKEA  https://github.com/Stevenleizheng/FEDKEA
        https://www.viromelab.com/software/fedkea
```

For candidate lists shorter than 20 sequences, FedKEA web server is usually the fastest validation route. For larger batches, install FedKEA locally and point `validation_inputs.fedkea.script_path` at its `main.py`.

For DEER checkpoints on a server without Hugging Face access, place the model files under the configured `tools.deer.ckpt_dir` and set `tools.deer.skip_hf_checkpoint: true` before running.

---

## Usage examples / 使用示例

以下示例按三种常见输入类型排列，均改写自真实可复现场的案例，方便你直接复制相近句式发起分析：

| 输入类型 | 触发点 | 举例 |
| --- | --- | --- |
| 已知代谢反应 | 有底物/产物，但没有明确模板序列或 EC。 | 神经酰胺合成 → ceramide + phosphocholine |
| 已知酶名/EC | 有酶功能或功能类别注释。 | neutral sphingomyelinase / EC 3.1.4.12 |
| 已知参考序列 | 有模板蛋白 FASTA 或 UniProt accession。 | DDC / P20711 |

每个示例都给出“用户可以直接发送的一句话 prompt”和“Agent 按插件 skill 实际会走的分析链”。实际运行时，把工具和数据路径替换成你自己的即可。

### Example 1: 从代谢反应出发，预测人体微生物是否编码相关基因

```text
User:
"已知代谢反应的产物为神经酰胺和磷酸胆碱，预测皮肤微生物
表皮葡萄球菌（GCF_038181645.1）是否含有相关代谢基因，
并给出可以验证的实验方案。"

Agent:
- 用 `build-target-function-card` 把
  sphingomyelin -> ceramide + phosphocholine 写成
  `target_function_card.json`
- 先跑 `scripts/preflight_inputs.py --project project.json`，检查候选基因组的
  `.faa`/`.ffn`/`.gbff` 和结构目录是否存在
- 用 `genome-search` / `genome-download` / `genome-annotation` 解析
  `GCF_038181645.1` 并准备候选 proteome
- 用 `screen-sequence-candidates` 先做 CD-HIT 去冗余（单基因组 100%，多基因组
  95%），再 DIAMOND 序列筛选
- 用 `parse_source_annotations.py` 收集 `.faa`/`.gbff` 已带的 protein/gene、EC、
  Pfam/InterPro/KEGG 等注释证据
- 检查候选结构文件是否存在：没有就先跑 `structure-prediction`
  （PDB > AlphaFold DB > homology model > de novo），有则用
  `screen-structure-candidates` 对全部候选结构直接 US-align
- US-align 候选不足时，明确原因后，经用户同意再跑 DEER fallback
- 合并 FedKEA、文献证据和已有注释，按结构优先原则排序
- 输出 `scored_candidates_full.tsv`、`experimental_hypotheses.tsv`
  和 `experimental_design.md`

回答会明确：
- 是否检出候选基因
- 代表候选 accession/locus_tag
- 证据链和置信度
- 可执行的实验验证方案
```

### Example 2: 从已知酶出发，预测人体微生物是否编码相关的代谢基因

```text
User:
"预测给出的三个皮肤微生物基因组（Streptococcus pyogenes、
Streptococcus thermophilus、Staphylococcus xylosus）是否含有
neutral sphingomyelinase 相关的代谢基因，并给出可以验证的
实验方案。"

Agent:
- 用 `build-target-function-card` 以 neutral sphingomyelinase /
  EC 3.1.4.12 建目标卡片
- 自动或手动准备参考酶集合，优先写明来源（NCBI/PDB/UniProt）
- 严格检查用户给的基因组和结构仓库路径，缺文件或空文件在重型流程前报错
- 对三个基因组分别跑 `screen-sequence-candidates`：先 CD-HIT 去冗余
  （单基因组 100%，多基因组 95%），再 DIAMOND 筛选
- 每个基因组先看有没有候选结构；没有就跑 `structure-prediction`，有则
  用 `screen-structure-candidates` 直接对所有候选结构 US-align
- 按基因组分别判断是否 US-align 合格候选不足；不足且用户同意时，
  才跑 DEER fallback（例如 Staphylococcus_xylosus 之前就是这样）
- 用 FedKEA 对最终候选做酶/EC 验证，并保留 binary/enzyme/probability 结果
- 用 `literature-evidence` 补充可验证的 PMID/DOI 证据链
- 用 `score_candidates.py` 排序，输出每个物种的候选表、代表候选与实验设计

回答会明确：
- 每个物种是否有候选
- 有候选/无候选的关键证据
- DEER fallback 是否被使用及其原因
- 后续实验建议
```

### Example 3: 从已知序列出发，预测人体微生物是否编码类似的代谢基因

```text
User:
"预测肠道微生物青春双歧杆菌 Bifidobacterium adolescentis
是否可能编码褪黑素合成的关键酶 DDC（P20711），并给出
可以验证的实验方案。"

Agent:
- 用 `build-target-function-card` 以 DDC / aromatic L-amino acid
  decarboxylase（EC 4.1.1.28）建目标卡片，UniProt 参考 = P20711
- 没有用户提供的 FASTA 时，先给 UniProt 获取命令，不要自己编序列
- 先跑 `scripts/preflight_inputs.py --project project.json`，检查候选基因组的
  文件和结构目录是否存在
- 用 `genome-search` / `genome-download` / `genome-annotation` 准备
  Bifidobacterium adolescentis 候选 proteome
- 用 `screen-sequence-candidates` 先 CD-HIT 去冗余（单基因组 100%，多基因组
  95%），再 DIAMOND 筛选
- 检查候选结构是否存在；无则跑 `structure-prediction`，有则用
  `screen-structure-candidates` 直接 US-align
- US-align 候选不足时，经用户同意再跑 DEER fallback
- 用 FedKEA 和已有注释/Pfam/InterPro 交叉核对
- 结合 `literature-evidence` 输出带 PMID/DOI 的证据链与最终排序

回答会明确：
- 是否检出 DDC 类候选
- 代表候选 accession/locus_tag
- 候选的序列/结构/FedKEA 证据链
- 验证 DDC/褪黑素合成的实验路径
```

---

### 如何把这些示例变成你自己的 demo

1. 在 `project.json` 中填入用户自己的数据路径和工具路径。
2. 如果目标不是 NSMase/DDC，修改 `inputs.target_sequence_fasta`、`reference_enzyme.enzyme_name`、`reference_enzyme.ec`，或用底物/产物起动。
3. 让 Agent 按主 skill 先跑 light 流程：CD-HIT + DIAMOND -> US-align -> 已有注释/FedKEA -> 文献证据/实验假设 -> 最终排序。
4. 实验方案由 Agent 结合已验证文献和实验体系生成；没有文献支持时不要伪造引用。

---

## Key outputs / 主要输出

- `target_function_card.json`
- `sequence_hits.tsv`
- `sequence_candidates.tsv`
- `structural_hits.tsv`
- `structural_candidates.tsv`
- `literature_evidence.tsv`
- `fedkea_results.tsv`
- `combined_candidates.tsv`
- `scored_candidates_full.tsv`
- `high_confidence_candidate_summary.tsv`
- `final_target_candidates.tsv`
- `experimental_hypotheses.tsv`
- `experimental_design.md`

`scored_candidates_full.tsv` is the final ranked candidate table. The compact deliverables `high_confidence_candidate_summary.tsv` and `final_target_candidates.tsv` point back to the full evidence table.

Raw tool output paths, tool names, versions, thresholds, and source annotations must be preserved in provenance fields. Sequence similarity, structural similarity, computational EC prediction, literature references, and existing annotations are evidence chains, not biochemical proof.

---

## Further documentation / 更多文档

- [QUICKSTART.md](QUICKSTART.md): install and first-use guide / 安装与上手。
- [DELIVERY.md](DELIVERY.md): delivery contents and adaptation guide / 交付内容说明。
- [scripts/README.md](scripts/README.md): parser and wrapper details / 脚本说明。
- [schemas/README.md](schemas/README.md): evidence-table contracts / Schema 说明。
- [references/tool_fallback.md](references/tool_fallback.md): tool-running and fallback policy / 工具运行策略。
- [references/literature_evidence.md](references/literature_evidence.md): verified literature evidence chain guide / 文献证据链说明。
- [references/acceptance_criteria.md](references/acceptance_criteria.md): task completion checklist / 验收标准。
