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
- 插件提供技能、脚本、schema 与资料，不替代 DIAMOND、CD-HIT、US-align、DEER、FedKEA、Bakta、SignalP 或文献数据库。
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
├── library/                     # curated selectable target index (domain -> process -> enzyme)
├── schemas/                     # machine-readable evidence-table contracts
├── scripts/                     # parsers, wrappers, ranking, and example test
├── projects/                    # example project configuration files
└── skills/                      # main skill plus independent sub-skills
```

---

## Two ways in / 两种进入方式

插件有两条**并列**的入口，走哪条完全看用户手里已经有什么，没有先后、没有主次：

| 用户手里有什么 | 走哪条 | 关键 skill |
| --- | --- | --- |
| **能说出目标**：酶名、EC 号、底物-产物反应、一段序列 | **入口 A · 显式建档**（直接开始，不经过目标库） | `build-target-function-card` |
| **只知道关注点**：某个生理过程、表型、身体部位，或一句「都有哪些关注的菌」 | **入口 B · 从目标库选**（把三层摊开给用户挑） | `browse-target-library` |

两条路在 `target_function_card.json` 汇合，之后的主流程完全一样。也可以叠加：入口 B 选完目标、用入口 A 复核字段。**已知目标时不要绕道目标库**——那是额外一步，没有收益。

---

## Skills / 技能

- `browse-target-library`: 入口 B。当用户还没给出具体的酶/EC/序列，只说了关注某个生理过程、表型或身体部位（例如「皮肤代谢有哪些重要的生理过程」「我关注油脂分泌」「哪些菌值得看」）时，用 `library/` 里的目标库把「身体部位 → 生理过程 → 酶目标」逐级摊开给用户挑，再导出 `target_function_card.json`。**已知目标时不需要这个 skill。**
- `build-target-function-card`: 入口 A。标准化目标输入，生成 Target Function Card；用户能说出酶/EC/反应/序列时从这一步直接开始。
- `functional-dark-matter-discover`: 主流程，负责把目标酶/EC/反应变成候选与实验设计。
- `screen-sequence-candidates`: 运行或消费 DIAMOND 序列筛选，默认先做 CD-HIT 去冗余；单菌单基因组默认 100%，多基因组泛蛋白组默认 95%。
- `structure-prediction`: 当候选蛋白没有已知结构文件时，按 PDB > AlphaFold DB（mean pLDDT >= 60）> homology model > de novo prediction 的优先级检索或预测结构；内置的 PDB/AFDB/homology 辅助脚本在 `skills/structure-prediction/scripts/` 中，为 US-align 准备 `structure/<protein_sequence_id>.pdb`。
- `screen-structure-candidates`: 结构证据筛选。先检查候选结构文件是否存在；没有结构文件时先运行内置 `structure-prediction` 子 skill 获取候选结构，再对全部候选结构直接 US-align；只有某个基因组**完全没有 US-align 合格候选、或合格候选不足**时，才按用户同意跑 DEER fallback。仅在“序列筛选 + 已有注释”没有共同确认目标功能时才启用。
- `prepare-cro-work-order`: 把目标与候选清单变成**可以直接发给公司询价和执行**的委托实验工作单（M1 基因合成 … M10 数据/生物安全），附逐字序列、预注册判定规则、术语表和「发出前必须确认」清单。价格与周期一律留空由承接方填写。
- `literature-evidence`: 文献证据审计。可用 MCP 文献工具时走 `nature-academic-search` 类流程，否则给出检索词或接收用户提供的已验证引用文件；禁止编造 PMID/DOI。
- `genome-search`: 从 NCBI Assembly/BioSample 元数据中选择候选 GCF/GCA。
- `genome-download`: 批量下载 RefSeq/GCF 或 GenBank/GCA 基因组文件。
- `genome-annotation`: 用 Bakta 给新下载基因组建库并注释。

The three genome sub-skills are independent deliverables. Load them when users have taxa or accession lists but do not already have a candidate proteome `.faa` or annotated `.gbff` dataset.

---

## Target library / 目标库（让用户「选」而不是「想」）

`library/` 是一个可浏览、可搜索、可选择的三层靶点索引（**可选入口 B**；已知目标时直接走入口 A，不需要它）：

```text
domain（身体部位）  ->  process（生理过程）  ->  enzyme（真正拿去筛的酶目标）
```

用户通常说不清自己要哪个酶，只会说「皮肤代谢有哪些重要的过程」「我关注油脂分泌」「哪些菌或哪些酶值得看」。这正是目标库要接住的话：先给 `process` 列表，再给该 process 下的 `enzyme` 目标，每个目标都带 EC 与 EC 置信度、反应、底物/产物、折叠提示、已知微生物代表、**推荐起手式**（`reaction` / `ec` / `sequence`）、`dark_matter` 标记、优先级、来源说明和一条可证伪的验证实验。

| 库文件 | 内容 | role |
| --- | --- | --- |
| `library/skin.json` | 皮肤：2 个过程 / 2 个酶目标，**每条带已验证 PMID**——鞘磷脂酶（EC 3.1.4.12）、组氨酸酶（EC 4.3.1.3） | `shipped_example` |
| `examples/unverified/*.json` | 旧的 27 条未带引用的策展条目（皮肤 10 过程 / 肠道 5 过程），**不默认加载** | 参考内容 |

**默认库刻意很小。** 它只放逐条有真实文献支撑的条目，用 `--require-evidence` 衡量是 2/2 通过。旧的 27 条没有引用，已移到 `examples/unverified/`，在那个门槛下会被全部隔离——所以不再摆在默认菜单里。

组氨酸酶那一条值得看它怎么写证据：宿主侧（角质层组氨酸→尿刊酸、UV 吸收）有直接文献；微生物侧只有细菌 HutH 的酶学表征（*P. putida*、*S. griseus*、*B. subtilis*），**皮肤菌是否贡献尿刊酸没有任何结论**。条目把这两层分开写在 `provenance_note_zh` 里，`key_taxa` 标为参考对照（attention=low），不假装皮肤菌已被证明。

**库整体是可选的。** 清空 `library/` 后插件仍能做完全部功能，只是没有「先看哪几个酶」的菜单：入口 A（EC/反应/序列）、按部位挑基因组、序列/结构/注释/文献证据、排序、外包工作单都不受影响。唯一可数的代价是 `--auto-score` 的自动分项从 8 项降到 4 项。空库是受支持状态——`--list-domains` 会打印"库为空、不是错误"和三条替代路径。

### 多个候选之间怎么排 / Ranking before screening

库给的是策展的 `priority` / `attention`，够用来「先看谁」，但不足以在十几个候选之间给出可辩护的排序。这时用**筛选前**的优先级排序：

```bash
# 从库生成打分骨架（分数留空，不替你编）
python3 scripts/score_target_priorities.py --seed-from-library library/skin.json --output outputs/task/priorities
# 按 0–5 给分项打分后排序
python3 scripts/score_target_priorities.py \
  --enzymes outputs/task/priorities/enzyme_registry.seed.tsv \
  --taxa outputs/task/priorities/taxa_registry.seed.tsv \
  --site skin --output outputs/task/priorities
```

产出 `enzyme_priority_ranking.tsv`、`taxa_priority_ranking.tsv`、`selected_taxa.tsv`、`selected_taxa.txt`（可直接喂给 `genome_source_search.py taxa --input`）、`ranking_report.md`。

这套打分模型整合自本地 `select-candidate` skill 并做了通用化，同时补上它缺的三件事：

1. **权重与分数分开，能自动算的不用手填**：权重是"标准"，分项分数是输入。`--auto-score` 会从已有产物推导 **6 项**——`biochemical_clarity` / `microbial_plausibility` / `novelty`（来自库条目）、`sequence_structure`（来自参考酶集合）、`genome_availability` / `site_presence`（来自 genome-search 结果），并在每行的 `score_sources` 里记明依据（`auto:library` 等）。其中 `site_evidence` 与 `disease_relevance` 两项可以来自**真实文献表**：先跑 `literature-evidence`，再用 `--literature outputs/task/literature_evidence.tsv [--disease "<表型>"]`。规则是只算 `verified=yes` 的功能性记录（`direct_functional_evidence` / `related_assay`）：1 条=3、2 条=4、≥3 条=5，只有 review 时=2；`no_evidence` 与未核实记录**不抬高分数**，也**不会变成 0**——没有证据不等于不重要，那两格会留成缺口。报告里会列出具体计入了哪些 reference、证据类型和是否已核实。`disease_relevance` 统计的是共现，不是因果。

剩下真正需要人判断的只剩 3 项：测活可行性、代谢合理性、菌株可操作性。任一必填分项既没给也无法推导时，脚本拒绝排序并逐格告诉缺哪个、用哪个 flag 可以补上；仍要排序就用 `--allow-missing-scores`，缺失项会记成 `missing` 并在报告里标红。
2. **主观性可见**：每一行都带 `score_basis = manual_expert_judgement` 与 `scoring_policy`（精确权重），任何排名都能被重算和质疑。
3. **阈值可达性校验**：原 skill 的示例配置把 `taxa_min_priority_score` 设成 948，而 0–5 分量表下的理论上限约 10.6——结果静默选出 0 个菌。现在这种情况直接报错并说明原因。
4. **兼容旧格式**：`skin_process` / `skin_evidence_score` / `skin_presence_score` 作为别名读取，原 `select-candidate` 的注册表可直接用。

排序只回答「先做谁」，不是功能证据。

### 库覆盖不到的方向怎么办 / Beyond the shipped domains

库只有 2 个部位、15 个过程，它是**内容**而不是**能力边界**。用户问牙周炎、阴道菌群、药物代谢时，插件不会哑掉，而是走三步升级：

| 问题形状 | 由什么机制接住 | 命令 |
| --- | --- | --- |
| 说了 EC / 反应 / 序列 | 入口 A，与库无关 | `build_target_function_card.py` |
| 点名了菌 | 部位通用：NCBI 按来源挑装配（内置 skin / oral / gut / respiratory / urogenital / blood / environment 七套来源词表） | `skills/genome-search/scripts/genome_source_search.py` |
| 只说了部位或表型，库没覆盖 | **路由**：判断问题形状，给出可执行步骤，并把部位/表型拼成文献检索词 | `scripts/resolve_target_intent.py --query "..."` |
| 想长期覆盖这个方向 | **按需扩库**：spec → 生成 starter 域 → 自动校验 | `scripts/build_library_domain.py` |

关键是这三步都**不产生事实断言**：路由只做问题分类和命令编排，扩库脚本拒绝空字段、强制 `content_status: starter`、强制清空 `evidence_refs`，并在写盘前跑真正的库校验。

```bash
# 任意问题先问路由器：它告诉你走哪条路、缺什么
python3 scripts/resolve_target_intent.py --query "口腔牙周炎相关菌有哪些酶值得看"
python3 scripts/resolve_target_intent.py --query "阴道菌群和乳酸杆菌" --json

# 想把口腔做成一个可选的部位：生成 spec → 填 → 构建（不通过就拒绝写盘）
python3 scripts/build_library_domain.py --init --domain oral --output specs/oral.json
python3 scripts/build_library_domain.py --build --spec specs/oral.json --output library/oral.json
python3 scripts/browse_target_library.py --validate
```

路由器的输出有一处刻意的设计：**跨部位命中不算覆盖**。问「阴道菌群」时，即使皮肤域有个「表面酸化」过程，它也只会标成 *usable as an analogy only, not as coverage*，然后走升级路径 —— 不会被当成答案。

**库是策展先验，不是文献证据。** `evidence_status` 默认为 `curated_prior`，`evidence_refs` 恒为空，只有 `literature-evidence` 真实检索到 PMID/DOI 后才允许升级为 `literature_verified`；`--validate` 会拒绝空引用或格式不像标识符的 `literature_verified`。`dark_matter: true` 的条目（例如体味 C-S 裂解酶、CutC、baiCD、LanB/LanC）刻意留空 EC，不允许借用邻近酶的 EC 号。新增身体部位只需新增一个 `library/<domain>.json`，不需要改代码；规则见 `library/README.md`。

---

## CRO work order / 外包实验工作单

`experimental_design.md` 是给**自己做实验的人**看的最小实验清单。用户如果不懂分子生物学、只想把实验交给公司做（基因合成、表达纯化、酶活检测），需要的是另一种东西：**一份能直接询价和下单的工作单**。

```bash
python3 scripts/build_cro_work_order.py \
  --card outputs/task/target_function_card.json \
  --candidates outputs/task/summary/final_target_candidates.tsv \
  --hypotheses outputs/task/summary/experimental_hypotheses.tsv \
  --sequences outputs/task/candidate_sequences/candidate_proteins.faa \
  --outdir outputs/task/cro_package \
  --scope candidates --bsl BSL-1
```

产出四份文件：

| 文件 | 内容 |
| --- | --- |
| `cro_work_order.md` | 给公司看的正文：项目目标、模块表、候选清单（含序列是否齐）、对照要求、**预先注册的判定规则**、「发出前必须确认」、术语表（一句话解释每个术语）、报价提问清单、边界声明 |
| `cro_modules.tsv` | 可逐条报价的模块表，一行一个模块 |
| `cro_sequences.faa` | **逐字**从候选 FASTA 复制的序列，头部带来源 |
| `cro_sequences.MISSING.md` | 没有序列时写这个文件，而不是给一段假序列 |
| `cro_gap_list.md` | 发出之前必须补齐的项 |

模块划分（`--scope` 决定包含哪些）：

| id | 模块 |
| --- | --- |
| M1 | 基因合成、密码子优化、克隆 |
| M2 | 催化残基突变体（阴性对照） |
| M3 | 小试表达与可溶性判定 |
| M4 | 放大表达与纯化 |
| M5 | 体外酶活方法建立（阳性对照） |
| M6 | 候选蛋白平行测活 |
| M7 | 对照体系与假阳性排除 |
| M8 | 扩展表征（底物谱、pH/温度、动力学） |
| M9 | 细胞或菌株水平验证（需专门 CRO） |
| M10 | 数据交付、生物安全、知识产权 |

三档 scope：`assay_first`（还没有候选，先用阳性对照酶把方法建起来）／`candidates`（默认，候选已知）／`full`（再加突变体、扩展表征、体内验证）。

三条硬边界，都由脚本强制：

1. **不写价格和周期**。所有价格格都是 `需询价 / quote required`，周期是 `待公司填写`。编一个数字比留空更糟——用户会拿它去做预算。
2. **不编造序列**。序列只从用户给的 FASTA 逐字复制；没有就写 `cro_sequences.MISSING.md`。一段看起来像真序列的假序列被拿去合成，会让整批实验白做。
3. **生物安全只是清单，不是结论**。文件预填 BSL 等级并列出必须由用户所在机构生物安全委员会确认的项，绝不断言"合规"或"豁免"。

判定规则来自 `experimental_hypotheses.tsv`，是**在数据回来之前**就写好的：什么算成立、什么算不成立、什么算"不可判定"（蛋白不溶或对照失效属于实验失败，不等于没有功能）。

---

## Core workflow / 核心流程

```text
entry A (user can name it):  target enzyme / EC / substrate-product / sequence
entry B (user only knows):   vague interest "油脂分泌" / "皮肤屏障" / "体味"
                               -> browse-target-library: domain -> process -> enzyme
  (both entries converge here)
  -> target_function_card.json
  -> preflight check .faa/.ffn/.gbff and structure paths
  -> optional genome-search / genome-download / genome-annotation
  -> CD-HIT deduplication (100% for single-genome datasets; 95% for multi-genome pan-proteomes)
  -> DIAMOND sequence screening
  -> parse existing .faa/.gbff annotations
  -> fast path: if sequence hit AND existing annotation match the target,
     mark SEQUENCE_ANNOTATION_CONFIRMED and skip structure steps
  -> otherwise check candidate structure files (PDB/CIF)
  -> if structures missing, run bundled structure-prediction sub-skill
  -> direct US-align against the reference target structure for all available candidate structures
  -> DEER only as fallback for genomes with no US-align candidate or too few of them,
     and when the merged sequence+structure candidate list has no qualifying candidate
  -> optional SignalP cleavage prediction for final candidate proteins
  -> optional catalytic-pocket, genome-context, and ecological evidence
  -> optional FedKEA enzyme/EC evidence
  -> literature-evidence audit (verified PMID/DOI evidence)
  -> merge combined_candidates.tsv
  -> explicit priority candidate ranking
  -> falsifiable experimental hypotheses
  -> experimental design
```

默认排序由 `scripts/score_candidates.py` 给出确定性的 `overall_rank`，**以结构相似性（TM-score）为主键**（`--rank-by structure`，默认）：有 TM 值的行按 TM 降序排在前；没有 TM 值的行（快速通道跳过结构的行、只有距离的 DEER 行、仅序列、仅注释）排在其后，内部再按 `priority_order`，然后按序列分、注释强度、`candidate_id` 破平。

之所以以 TM 而非 `priority_rule` 层级为主键：对**趋同/兼职酶**靶点，被验证的酶往往自带一个与目标 EC **不同**的注释和 FedKEA EC，按层级优先会把真阳性压到「EC 恰好对上」的候选之后。需要旧行为时用 `--rank-by priority` 恢复层级优先排序。`priority_rule`/`priority_order`/`rank_policy` 作为溯源列保留，最终对外交付仍以 `overall_rank` 为准。

如果 DIAMOND 序列命中且 `.faa`/`.gbff` 已有注释同时匹配目标功能，该候选走 `SEQUENCE_ANNOTATION_CONFIRMED` 快速路径、不做结构比对（因此没有 TM 值，落在无 TM 组内按优先级居首）；只有序列和注释证据不足或不一致时才进入结构证据流程。

The final ranked table is `scored_candidates_full.tsv`, with `overall_rank` as the explicit deliverable ranking field. `priority_rule` / `priority_order` / `rank_policy` are retained for traceability. Ranking is TM-score-first by default; pass `--rank-by priority` to sort by the priority tier instead.

Priority policy used by `score_candidates.py`:

1. `SEQUENCE_ANNOTATION_CONFIRMED`
2. `USALIGN_TARGET_EC`
3. `DEER_FEDKEA_CONFIRMED`
4. `USALIGN_OTHER_EC`
5. `USALIGN_NOT_ENZYME`
6. `USALIGN_UNVALIDATED`
7. `DEER_FALLBACK`
8. `SEQUENCE_ONLY`
9. `ANNOTATION_ONLY`

---

## Tool execution boundary / 工具执行边界

The plugin does not silently download or install DIAMOND, CD-HIT, US-align, DEER, FedKEA, or Bakta.

1. 先向用户索取**具体位置**：数据文件路径 **和** 所需软件的可执行文件路径（DIAMOND/CD-HIT/US-align，可选 DEER/FedKEA/Bakta/SignalP，含版本与 `auto_run_local` 意图）。路径缺失、仍是示例占位符 `/path/to/...`、或位于远程主机时，都要明确询问，不要让用户猜、也不要自行假设。清单见
   [`references/input_paths.md`](references/input_paths.md)。
2. 若数据/工具在**远程主机**上，请用户给出 `user@host` 与该主机上的绝对路径，并先确认可访问，再执行。
3. 检查可执行文件与所需输入从当前终端是否可达：`python3 scripts/preflight_inputs.py --project project.json --require-tools`
   会为每个已配置的数据与工具路径报告 `ok` / `placeholder` / `missing` / `invalid`。
4. 可达且 `auto_run_local` 已启用时，直接运行并把命令与版本记入 provenance。
5. 可达但用户只想要命令，或不可达时，写出确切的待运行命令，等待用户返回结果文件。
6. 绝不编造工具输出。绝不程序化调用 FedKEA 网页服务器。

For structure evidence, first check whether candidate structure files (PDB/CIF)
exist. Skip this structure route entirely when a candidate already has a DIAMOND
sequence hit and its existing `.faa`/`.gbff` annotation matches the target
function. If a candidate lacks a structure, run the bundled `structure-prediction`
sub-skill (experimental PDB > AlphaFold DB model passing `mean pLDDT >= 60` >
homology model > de novo) and continue only after the returned structures are
materialized as `structure/<protein_sequence_id>.pdb`. Then use US-align on all
available candidate structure files. Use DEER only for a genome when US-align
yields no qualifying candidate for that genome, or not enough of them, and the user agrees.

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
- optional local SignalP executable under `tools.signalp`

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
python3 human_microbiome_function_mining/scripts/run_signalp.py --project project.json
```

DEER 的第二道门（合并后无合格候选时触发）需要传入合并表：

```bash
python3 human_microbiome_function_mining/scripts/run_deer.py \
  --project project.json \
  --combined-candidates outputs/task/combined_candidates.tsv
```

`--template-dir` / `--candidate-dir` / `--outdir` / `--usalign-dir` 省略时会从 `project.json` 读取，所以上面两个参数即完整调用。

External tool sources:

```text
DEER    https://github.com/WangJiuming/deer
FedKEA  https://github.com/Stevenleizheng/FEDKEA
        https://www.viromelab.com/software/fedkea
SignalP https://services.healthtech.dtu.dk/services/SignalP-6.0/
```

For candidate lists shorter than 20 sequences, FedKEA web server is usually the fastest validation route. For larger batches, install FedKEA locally and point `validation_inputs.fedkea.script_path` at its `main.py`.

FedKEA should normally be run on the candidate protein FASTA produced by
`extract_candidate_sequences.py`, not on the full proteome, unless the user
explicitly requests a whole-proteome enzyme scan. Candidate FASTA headers must
keep the accession as the first field (for example `>WP_...`), and the wrapper
can verify output accession joinability with `--expected-accessions` (or
`validation_inputs.fedkea.expected_accessions` in `project.json`).

For DEER checkpoints on a server without Hugging Face access, place the model files under the configured `tools.deer.ckpt_dir` and set `tools.deer.skip_hf_checkpoint: true` before running.

---

## Usage examples / 使用示例

**一共 4 个示例，对应 3 种起手式。** 均改写自真实可复现场的案例，方便你直接复制相近句式发起分析：

| # | 输入类型 | 触发点 | 举例 | 起手式 |
| --- | --- | --- | --- | --- |
| 1 | 已知代谢反应 | 有底物/产物，但没有明确模板序列或 EC | sphingomyelin → ceramide + phosphocholine | `reaction` |
| 2 | 已知酶名/EC | 有酶功能或功能类别注释 | neutral sphingomyelinase / EC 3.1.4.12 | `ec` |
| 3 | 已知参考序列 | 有模板蛋白 FASTA 或 UniProt accession | DDC / P20711 | `sequence` |
| 4 | 已知参考序列（家族很大） | 同 3，但靶点属超大超家族（本例 GNAT/PF00583） | AANAT / Q16613 | `sequence` + 家族普查 |

第 3、4 个都落在"褪黑素通路"上，但结论完全不同：DDC 那个是**证据不足、需要测酶活**；AANAT 那个要额外做**家族普查**，因为序列层可能没有显著命中，而"没有正统同源物"不等于"没有该活性"。

每个示例都给出“用户可以直接发送的一句话 prompt”和“Agent 按插件 skill 实际会走的分析链”。实际运行时，把工具和数据路径替换成你自己的即可。

### Example 1: 从代谢反应出发，预测人体微生物是否编码相关基因

```text
User:
"已知代谢反应的产物为神经酰胺和磷酸胆碱，预测皮肤微生物
表皮葡萄球菌（GCF_038181645.1）是否含有相关代谢基因，
并给出可以验证的实验方案。"

Agent:
- 用 `build-target-function-card` 由产物反推反应 sphingomyelin + H2O -> ceramide + phosphocholine（EC 3.1.4.12），写成 `target_function_card.json`
- 输入清点：把候选蛋白组/基因组、目标序列、目标结构、候选结构目录分成已提供 / 待获取；「已提供」的一律直接用，不下载、不重注释、不预测、不覆盖；仅对「待获取」的候选用 `genome-search` / `genome-download` / `genome-annotation`
  准备候选 proteome；参考酶集同理，用户已给目标序列/结构时直接加载
- 用 `preflight_inputs.py` 校验并固化这个划分，缺文件或空文件在重型流程前报错
- 用 `screen-sequence-candidates` 先 CD-HIT 去冗余（单基因组 100%），再 DIAMOND 序列筛选
- 用 `parse_source_annotations.py` 解析 `.faa`/`.gbff` 已有的 protein/gene、EC、Pfam/InterPro/KEGG 注释
- 快速通道优先：DIAMOND 命中且注释匹配目标即标记 `SEQUENCE_ANNOTATION_CONFIRMED`
- 用 `literature-evidence` 补充可验证的 PMID/DOI 证据链（只保留核验过的）
- 用 `score_candidates.py` 按优先级规则排序，输出 `scored_candidates_full.tsv`、`experimental_hypotheses.tsv` 和 `experimental_design.md`

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
- 用 `build-target-function-card` 以 neutral sphingomyelinase /EC 3.1.4.12 建目标卡片
- 自动或手动准备参考酶集合，优先写明来源（NCBI/PDB/UniProt）
- 严格检查用户给的基因组和结构仓库路径，缺文件或空文件在重型流程前报错
- 跑重流程前执行 `preflight_inputs.py`，对三个基因组逐个核对 `.faa`、`.ffn`、`.gbff` 和候选结构目录
- 对三个基因组分别跑 `screen-sequence-candidates`：先 CD-HIT 去冗余（100%），再 DIAMOND 筛选
- 先看每个 DIAMOND 命中是否已有注释匹配 neutral sphingomyelinase /EC 3.1.4.12；只有序列无命中、或命中但注释不匹配时，才检查全部候选结构文件；
- 缺少结构就跑 `structure-prediction`，随后用 `screen-structure-candidates` 对当前基因组所有候选结构文件直接 US-align；按基因组分别判断：某基因组完全没有 US-align 合格候选、或合格候选不足；此时经用户同意才跑 DEER fallback
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
"预测给定的肠道微生物青春双歧杆菌 Bifidobacterium adolescentis
是否可能编码人类褪黑素合成的关键酶 DDC（P20711），并给出
可以验证的实验方案。"

Agent:
- 用 `build-target-function-card` 以 DDC / aromatic L-amino acid decarboxylase（EC 4.1.1.28）建目标卡片，UniProt 参考 = P20711
- 没有用户提供的 FASTA 时，先给 UniProt 获取命令，不要自己编序列；如项目配置了参考酶抓取，也会用 `fetch_reference_enzymes.py` 自动准备参考酶记录
- 先跑 `scripts/preflight_inputs.py --project project.json`，检查候选基因组的文件和结构目录是否存在
- 用 `screen-sequence-candidates` 先 CD-HIT 去冗余（单基因组 100%），再 DIAMOND 筛选
- 先检查 DIAMOND 命中是否已有 P20711/DDC 相关注释；匹配则标记 `SEQUENCE_ANNOTATION_CONFIRMED` 并跳过结构流程
- 只有序列无命中、或命中但注释不匹配时，才用 `screen-structure-candidates` 对全部候选结构文件直接 US-align
- 用 FedKEA 和已有注释/Pfam/InterPro 交叉核对
- 用 `literature-evidence` 审计文献并输出带 PMID/DOI 的证据链，随后用 `score_candidates.py` 做最终排序（默认以 TM-score 为主键；`--rank-by priority` 可回到优先级规则排序）

回答会明确：
- 是否检出 DDC 类候选
- 代表候选 accession/locus_tag
- 候选的序列/结构/FedKEA 证据链
- 验证 DDC/褪黑素合成的实验路径
```

---

### Example 4: 从一个"酶家族很大"的靶点出发，预测肠道微生物是否编码同类活性的酶

```text
User:
"预测给定的肠道微生物青春双歧杆菌 Bifidobacterium adolescentis
是否可能编码人类褪黑素合成的关键酶 AANAT（Q16613），并给出
可以验证的实验方案。"

Agent:
- 用 `build-target-function-card` 以 AANAT / aralkylamine N-acetyltransferase（EC 2.3.1.87）建目标卡片，UniProt 参考 = Q16613，并记下辅因子 acetyl-CoA 与折叠 GNAT（Pfam PF00583）
- 参考酶集合仅保留靶点参考：人类 human AANAT（reviewed EC 2.3.1.87），不设折叠对照
- 先跑 `scripts/preflight_inputs.py --project project.json --require-target-sequence --require-target-structure`，核对候选基因组文件与候选结构目录
- 用 `screen-sequence-candidates` 先 CD-HIT 去冗余（单基因组 100%），再 DIAMOND 筛选；除默认阈值外，再补一次 `--sensitive`（宽 E 值）扫"远缘同源尾巴"，并把两次结果分开报告
- 因为靶点属于 GNAT 超家族，先做家族普查：用 Pfam PF00583（`hmmsearch`）枚举候选基因组里的全部 GNAT 蛋白，并在同一次检索中带上阳性对照（仅人 AANAT）；这一层定义候选全集，而不是 DIAMOND 命中表（注意：`hmmsearch` **未随插件打包**，按工具执行边界处理——本机可用就直接跑，否则把上面的命令交给你执行后再读回结果）
- 序列层若无显著命中（本例正是如此），用 `screen-structure-candidates` 对全部候选结构做 US-align，只用靶点模板；靶点模板优先用实验结构（如 1CJW/1KUV），当预测模型与实验结构给出的排序不一致时以实验结构为准
- 用 FedKEA 交叉核对（要带上正确环境、并提交 accession 干净的 FASTA 表头）；FedKEA 给出的是最可能的单一 EC（正统功能），不能用来排除兼职活性
- 用 `literature-evidence` 审计文献并输出带 PMID/DOI 的证据链，随后用 `score_candidates.py` 做最终排序（默认以 TM-score 为主键；`--rank-by priority` 可回到优先级规则排序）

回答会明确：
- 是否存在 AANAT 的正交同源物，以及候选全集（GNAT 家族成员数）
- 代表候选 accession 与基因坐标，及其序列/结构/FedKEA 证据链
- 哪些候选已有文献实验验证、哪些仍只是假设
- 验证 5-羟色胺/色胺乙酰化的实验路径（重组表达 + LC-MS/MS 产物确证 + 动力学与已知细菌 SNAT 比较 + 敲除/回补）
```

> 与 Example 3 的关键差别：靶点属于超大超家族时，必须额外加一步 —— **家族普查（Pfam HMM）**；结论也要把"没有正统同源物"和"没有该活性"分开说。

### 如何把这些示例变成你自己的 demo

1. 在 `project.json` 中填入用户自己的数据路径和工具路径。
2. 如果目标不是 NSMase/DDC，修改 `inputs.target_sequence_fasta`、`reference_enzyme.enzyme_name`、`reference_enzyme.ec`，或用底物/产物起动。
3. 让 Agent 按主 skill 先跑 light 流程：CD-HIT + DIAMOND -> 已有注释匹配（可走
   `SEQUENCE_ANNOTATION_CONFIRMED` 快速路径）-> 必要时才 US-align / DEER -> FedKEA
   -> 文献证据/实验假设 -> 最终排序。
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
- `candidate_sequences/candidate_proteins.faa`
- `candidate_sequences/candidate_cds.ffn`
- `candidate_sequences/candidate_gene_sequences.fna`
- `candidate_sequences/candidate_mature_proteins.faa` (SignalP-cleaved secreted proteins only)
- `candidate_sequences/candidate_gene_evidence.tsv`

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
