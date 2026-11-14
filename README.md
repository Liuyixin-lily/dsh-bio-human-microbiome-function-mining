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

插件有两条入口，按用户手里已经有什么来分。它们不是两套流程：**入口 B 收敛到具体目标后会交棒给入口 A**（`run_entry_b.py --select <id> --ec <EC>`）。

| 用户手里有什么 | 走哪条 | 关键 skill |
| --- | --- | --- |
| **能说出目标**：酶名、EC 号、底物-产物反应、一段序列 | **入口 A · 显式建档**（直接开始，不经过目标库） | `build-target-function-card` |
| **只知道关注点**：某个生理过程、表型、身体部位，或一句「都有哪些关注的菌」 | **入口 B · 从目标库选**（把三层摊开给用户挑） | `browse-target-library` |

两条路在 `target_function_card.json` 汇合，之后的主流程完全一样。也可以叠加：入口 B 选完目标、用入口 A 复核字段。**已知目标时不要绕道目标库**——那是额外一步，没有收益。

---

## Before anything runs / 先问环境（但先定目标）

**顺序是「先定目标、再按需问环境」。** 环境问卷要按任务裁剪——目标只是建卡片时，不问 Bakta、不问 DEER；不问清目标就问一圈服务器与数据库，是让用户为用不上的路径买单。

插件不捆绑重型工具，所以「能不能跑」必须先问清楚，而不是假设。真实项目里最耗时的失败都属于这一类：工具用绝对路径调用但 conda 环境没进 PATH（`foldseek: command not found`）、另一个工具缺 `PYTHONPATH`、某个工具在**无外网**的机器上卡在连 HuggingFace 取 checkpoint、Bakta 因为 `BAKTA_DB_FULL` 没设而跑不起来、共享机器上已有 146 个别人的进程。

```bash
# 先按任务裁剪：card 不碰任何外部软件；screening 只要 DIAMOND/CD-HIT；structure 再加 US-align
python3 scripts/intake_environment.py --ask --task card
python3 scripts/intake_environment.py --ask --task screening
python3 scripts/intake_environment.py --ask --task structure
python3 scripts/intake_environment.py --ask          # 完整问卷（6 组），需要时再补问

python3 scripts/intake_environment.py --init --output environment.json
python3 scripts/intake_environment.py --probe --config environment.json \
    --output-card environment_card.json --output-report environment_report.md
```

| 状态 | 含义 | 允许做什么 |
| --- | --- | --- |
| `ready` | 可执行文件存在**且**能报出版本号（含数字） | 允许执行时才可运行 |
| `unverified` | 能运行但报不出版本，或声明的环境变量路径不存在 | 不算可用，需用户确认或最小样例试跑 |
| `missing` | 声明了但找不到 | 只给命令 |
| `not_provided` | 用户说没有 | 只给命令 |

**这些文件是每个用户自己的，不能预填、不能提交。** `environment.json` / `environment_card.json` / `config.tools.json` 描述的是**某一台机器**，已在 `.gitignore` 里；插件本身只带问卷和全 `null` 的骨架。给插件做示例时用 `/path/to/...` 占位符，并用这条审计兜底（测试里也会跑）：

```bash
python3 scripts/intake_environment.py --audit-paths .
```

它会在出现真实主目录（`/Users/<name>/`、`/home/<name>/`）或私有网段地址时报错退出。

同一份回答还能直接生成 `project.json` 需要的 `tools` / `inputs` 片段，不用填两遍：

```bash
python3 scripts/intake_environment.py --probe --config environment.json \
    --output-card environment_card.json --emit-config outputs/task/config.tools.json
```

规则同上：**只有 `ready` 的工具才写路径**，其余留空并 `enabled: false`；DIAMOND 就绪但 CD-HIT 缺失时 `sequence_screen` 仍为禁用（去冗余是强制步骤）；环境变量路径不存在的工具保留 `env` 便于修正但不算启用。

两条硬规则：**路径存在 ≠ 能跑**（报不出版本就记 unverified，因为问题通常要到运行时才暴露）；**执行许可与能力是两件事**——`allow_local_execution` 不为 true 时，无论工具多齐都只产出命令清单。`--check-network` 可探测 NCBI / RCSB / HuggingFace 可达性，涉及自动下载的步骤必须先确认。

## Skills / 技能

- `intake-environment`: **跑任何工具之前的第一步**。先问用户：在哪跑（本机 / 远程 host / 你手动跑）、机器资源、每个外部软件的绝对路径与所需环境变量、数据库路径、数据路径、能否联网。回答写进 `environment.json`，再用 `--probe` 逐项验证。只有 `ready` 的工具、且 `allow_local_execution` 明确为 true 时才在本机运行。
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
| `library/skin.json` | 皮肤：1 个过程 / 1 个酶目标，**带已验证 PMID**——鞘磷脂酶（EC 3.1.4.12），正好对应示例 1/2 | `shipped_example` |
| `examples/unverified/*.json` | 旧的 27 条未带引用的策展条目（皮肤 10 过程 / 肠道 5 过程），**不默认加载** | 参考内容 |

**默认库刻意很小。** 它只放逐条有真实文献支撑、且与示例对得上的条目，用 `--require-evidence` 衡量是 1/1 通过。旧的 27 条没有引用，已移到 `examples/unverified/`，在那个门槛下会被全部隔离——所以不再摆在默认菜单里。

**库整体是可选的。** 清空 `library/` 后插件仍能做完全部功能，只是没有「先看哪几个酶」的菜单：入口 A（EC/反应/序列）、按部位挑基因组、序列/结构/注释/文献证据、排序、外包工作单都不受影响。唯一可数的代价是 `--auto-score` 少 4 个可从库推导的分项（`biochemical_clarity`、`microbial_plausibility`、`novelty` 属于酶，`metabolic_plausibility` 属于菌），其余仍可从文献、参考酶和 genome-search 推导。空库是受支持状态——`--list-domains` 会打印"库为空、不是错误"和三条替代路径。

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

1. **权重与分数分开，能自动算的不用手填**：权重是"标准"，分项分数是输入。`--auto-score` 最多能推导 **9 个分项**，每个都在 `score_sources` 里写明依据：

   | 分项 | 表 | 来源 |
   | --- | --- | --- |
   | `biochemical_clarity` | 酶 | 库条目 `ec_confidence`/反应；或文献发现的注册表 `ec_confidence`（`auto:registry`） |
   | `microbial_plausibility` | 酶 | 库条目的已知微生物实例；或注册表的 `microbial_context` |
   | `novelty` | 酶 | 库条目是否 dark matter / 有已知实例 |
   | `site_evidence` | 酶 | 库条目的 `evidence_status` + `evidence_refs`；或真实文献表 |
   | `disease_relevance` | 酶 | 真实文献表（共现，不是因果） |
   | `sequence_structure` | 酶 | 参考酶集合是否有序列/结构 |
   | `genome_availability` | 菌 | genome-search 结果 |
   | `site_presence` | 菌 | genome-search 结果（direct 命中的比例） |
   | `metabolic_plausibility` | 菌 | 库的 `focus_taxa` 及其 attention |

   仍**只能手填**的三项：`assay_feasibility`（酶）、`experimental_accessibility` 与 `disease_site_relevance`（菌）——插件不替你判断"这个实验好不好做"。

   文献表的计分规则：只算 `verified=yes` 的功能性记录（`direct_functional_evidence` / `related_assay`）：1 条=3、2 条=4、≥3 条=5，只有 review 时=2；`no_evidence` 与未核实记录**不抬高分数**，也**不会变成 0**——没有证据不等于不重要，那两格会留成缺口。报告里会列出具体计入了哪些 reference、证据类型和是否已核实。`disease_relevance` 统计的是共现，不是因果。

真正需要人判断的只有 3 项：测活可行性（`assay_feasibility`）、菌株可操作性（`experimental_accessibility`）、疾病-部位相关性（`disease_site_relevance`）。任一必填分项既没给也无法推导时，脚本拒绝排序并逐格告诉缺哪个、用哪个 flag 可以补上；仍要排序就用 `--allow-missing-scores`，缺失项会记成 `missing` 并在报告里标红。
2. **主观性可见**：每一行都带 `score_basis = manual_expert_judgement` 与 `scoring_policy`（精确权重），任何排名都能被重算和质疑。
3. **阈值可达性校验**：原 skill 的示例配置把 `taxa_min_priority_score` 设成 948，而 0–5 分量表下的理论上限约 10.6——结果静默选出 0 个菌。现在这种情况直接报错并说明原因。
4. **兼容旧格式**：`skin_process` / `skin_evidence_score` / `skin_presence_score` 作为别名读取，原 `select-candidate` 的注册表可直接用。

排序只回答「先做谁」，不是功能证据。

### 库覆盖不到的方向怎么办 / Beyond the shipped domains

库只有 2 个域、7 个过程（其中 1 个是逐条带 PMID 的 curated 域，1 个是 6 类的 starter 域），它是**内容**而不是**能力边界**。用户问牙周炎、阴道菌群、药物代谢时，插件不会哑掉，而是走三步升级：

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

## 交付集 / the delivery set

一次跑完的运行，`outputs/task/` 必须有这四样（另有 scored 表）：

| 文件 | 说明 |
| --- | --- |
| `final_target_candidates.tsv` | 最终候选；为空时**必须**有下面的说明 |
| `final_target_candidates_note.md` | 最终表为空时解释原因（"空"≠"没有"） |
| `high_confidence_candidate_summary.tsv` | 每个候选的证据摘要 |
| `experimental_hypotheses.tsv` | 可验证的实验假设 |
| `scored_candidates.tsv`（或 `scored.tsv`） | 打分表 |

跑完自查：

```bash
python3 scripts/check_deliverables.py --project-dir <项目目录>
```

它逐项报 ok / EMPTY / MISS，并对缺的项给出生成命令；四个示例里曾有三个卡在不同阶段，
正是因为没人检查这一步。

## B → A：选完候选后交棒 / after the ranking, hand off to entry A

入口 B 出排序表，你选一条，然后用同一个命令交棒给入口 A（建档 → 取模板 → 筛选 → 评分 → 汇总）：

```bash
# 第一次：只出候选清单
python3 scripts/run_entry_b.py --topic "Staphylococcus epidermidis 的醇脱氢酶" --site skin \
    --output-dir outputs/task/adh

# 选好 target_id 之后：交棒入口 A（用 --select）
python3 scripts/run_entry_b.py --topic "Staphylococcus epidermidis 的醇脱氢酶" --site skin \
    --select <target_id> --ec 1.1.1.1 --proteome <候选蛋白组>.faa \
    --output-dir outputs/task/adh
```

`--select` 只从上一轮的表里读那一行的名称/EC/证据，不重新推导；若该行没有 EC，它会停下来要你给 EC（同族不同 EC 底物不同）。

## Entry B in one command / 入口 B 一条命令

只给关注点，剩下按固定路线走完：

```bash
python3 scripts/run_entry_b.py --topic "皮肤外源性物质代谢" --site skin \
    --output-dir outputs/task/entry_b
```

它会：查库菜单 → 命中就用库里的域作种子；没命中就跑文献发现（中文题目先按固定词表转成英文检索词，
转不出来就问你，不猜）→ `score_target_priorities --auto-score` → 输出
`recommended_enzymes.tsv` / `recommended_taxa.tsv`，并打印成表格供你挑选。

## Candidate lists / 候选清单

入口 B 的产出是两张清单，而不是一个结论：

候选酶不必来自别人给的清单，插件可以自己从文献生成：

```bash
python3 scripts/discover_enzyme_candidates.py --site skin \
    --terms "skin microbiome xenobiotic metabolism enzyme" --limit 25 \
    --output outputs/task/discovery/enzyme_registry.tsv \
    --evidence outputs/task/discovery/literature_evidence.tsv
```

它只记录检索到的摘要里**实际出现**的酶名；EC 只在与酶名同一句时记录；每个候选都带 PMID 和原文句子。

```bash
python3 scripts/build_candidate_shortlist.py --site skin \
    --enzymes <你的酶表>.tsv --enzymes <库导出的注册表>.tsv \
    --taxa <位点菌名单>.tsv --library library/<domain>.json \
    --output-dir outputs/task/candidates
```

产出 `candidate_enzymes.tsv` / `candidate_taxa.tsv` / `candidate_shortlist.md`，分两段：

1. **recommended**：`literature_verified` 且带真实引用的条目
2. **candidate_pool**：用户提供的排序表、starter 域条目——每条都标注 `evidence_status` 与 `evidence_refs`

排序**证据优先**，因为分数跨来源不可比：旧的人工打分表把七项都填满了，而 starter 条目只有可推导的两项，单按分数排会把"没证据但打分高"的排到"有文献"的前面。

## Judgment points / 判断题

插件不替你做的判断，全部选项化并记录在 `environment.json` 的 `decisions`。**它们按阶段提问，不是一开始全问完**：`start` 阶段只问候选数据；`structure` 阶段问结构文件与结构来源；US-align 候选不足时才问是否启用 DEER；排序与交付各自在对应步骤问。

走到某一步而该判断还没答时，脚本会**停下打印选项**（`DECISION REQUIRED`）而不是用默认值继续：`run_deer.py` 退出码 3、`summarize_candidates.py` 在交付表为空时、`run_usalign.py` 在结构目录为空时。`--probe` 把未选报成 `needs_decision`——没选不等于同意。完整清单与"为什么必须问"见 `references/decision_points.md`。

## Evidence gate / 证据门槛

排序器默认会在证据很少时照样给名次。两种门槛可以拦住这种行为：

```bash
python3 scripts/score_target_priorities.py --taxa outputs/taxa/oral_taxa_registry.tsv \
    --site oral --auto-score --allow-missing-scores \
    --require-min-criteria 3 --output outputs/task/priorities
```

| 参数 | 含义 |
| --- | --- |
| `--require-min-criteria N` | 至少 N 个分项有值（人工判断也算） |
| `--require-min-evidence N` | 至少 N 个分项是**数据推导**的（只算 `auto:*`，人工判断不算） |

两者意义不同：前者防"几乎空白也排名"，后者防"全靠主观打分排序"。被扣下的行**不给名次**、也永远不会是 `selected`，但仍留在表里（隐藏掉会让输出看起来比证据更完整），原因写进 `withheld_rows.tsv`：

```
taxa_priority_ranking  haemophilus_haemolyticus  只有 1/5 项有值（要求 3）
```

若无一行达标，脚本会明说「不是没有候选，而是证据不足以排序」，而不是输出一张空表。

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
entry A (user can name it):  enzyme / EC / substrate-product / sequence
entry B (user only knows):   vague interest "油脂分泌" / "皮肤屏障" / "体味"
                               -> browse-target-library: domain -> process -> enzyme
  (both entries converge here)
  -> 模板序列 + 结构文件（宿主模板 + 微生物模板，人工策展或 fetch_reference_enzymes.py
     抓取；只收有实验证据的 reviewed 条目，TrEMBL 的 "Inferred from homology" 不入模板；
     结构文件取自 UniProt 的 PDB 交叉引用，US-align 需要它而不能只靠 FASTA）
  -> CD-HIT 去冗余（单基因组 100%；同一物种多个 GCF 的 pan-proteome 95%）
  -> DIAMOND 序列筛选（identity ≥ 0.2，query coverage ≥ 0.7，E ≤ 1e-5）
  -> parse_source_annotations（.faa/.gbff 已有注释作为独立证据）
  -> 【快速通道】序列命中 + 注释同向 -> SEQUENCE_ANNOTATION_CONFIRMED
       -> 直接跳过结构分析，给出结果
     （注释不匹配或无注释时才进入结构分析）
  -> 询问用户：有没有候选菌的蛋白结构文件？
       ├─ 没有 -> structure-prediction
       │          （PDB 实验结构 > AlphaFold DB pLDDT ≥ 60 > 同源建模 > de novo）
       └─ 有   -> 直接 US-align 全量（TM ≥ 0.5，双向）
                   -> 合格候选不足、且用户同意时，才启用 DEER fallback
  -> FedKEA（酶/EC 补充证据）/ SignalP（信号肽）
  -> literature-evidence（只保留核验过的 PMID/DOI）
  -> merge combined_candidates.tsv
  -> score_candidates.py --project project.json（从目标卡片取 EC/酶名，
     否则快速通道无法判定）-> 显式优先级排序（默认 TM 主键）
  -> 可证伪假设 + 实验设计
```

**跑之前必须先问清两件事**（详见 `references/data_intake.md`）：候选数据（蛋白组/基因组）的路径、以及有没有候选菌的结构文件。这两件事在插件里是**选择题**，写进 `environment.json` 的 `decisions`，由 `--probe` 校验：`candidate_data` 选 `user_path` / `download_ncbi` / `not_available`，`candidate_structures` 选 `user_path` / `predict` / `skip`。选了 `user_path` 却没给路径会报 `needs_field`，没选会报 `needs_decision`——**没选永远不等于同意**。另有代码闸门：`preflight_inputs.py --require-candidate-data` / `--require-candidate-structures`，`run_usalign.py` 在结构目录为空时打印问句并写 `blocked` checkpoint。替用户下载一个蛋白组、或假定"没有结构"就跳过结构层，都会让结果看起来正常但其实不是他要的。

流程的起点是**模板序列文件**，不是单条目标序列：判断「微生物是否编码人体相关的酶」时，需要同时拿宿主自身的酶和微生物的同源酶做模板——前者回答"是否与人体酶同源"，后者回答"是否是同类酶"。只取一组会漏。

默认排序由 `scripts/score_candidates.py` 给出确定性的 `overall_rank`，**以结构相似性（TM-score）为主键**（`--rank-by structure`，默认）：有 TM 值的行按 TM 降序排在前；没有 TM 值的行（快速通道跳过结构的行、只有距离的 DEER 行、仅序列、仅注释）排在其后，内部再按 `priority_order`，然后按序列分、注释强度、`candidate_id` 破平。

之所以以 TM 而非 `priority_rule` 层级为主键：对**趋同/兼职酶**靶点，被验证的酶往往自带一个与目标 EC **不同**的注释和 FedKEA EC，按层级优先会把真阳性压到「EC 恰好对上」的候选之后。需要旧行为时用 `--rank-by priority` 恢复层级优先排序。`priority_rule`/`priority_order`/`rank_policy` 作为溯源列保留，最终对外交付仍以 `overall_rank` 为准。

如果 DIAMOND 序列命中且 `.faa`/`.gbff` 已有注释同时匹配目标功能，该候选走 `SEQUENCE_ANNOTATION_CONFIRMED` 快速路径、不做结构比对（因此没有 TM 值，落在无 TM 组内按优先级居首）；只有序列和注释证据不足或不一致时才进入结构证据流程。

The final ranked table is `scored_candidates_full.tsv`, with `overall_rank` as the explicit deliverable ranking field. `priority_rule` / `priority_order` / `rank_policy` are retained for traceability. Ranking is TM-score-first by default; pass `--rank-by priority` to sort by the priority tier instead.

Priority policy used by `score_candidates.py`:

1. `SEQUENCE_ANNOTATION_CONFIRMED`
2. `USALIGN_TARGET_EC`
3. `DEER_FEDKEA_CONFIRMED`
4. `USALIGN_OTHER_EC`（**不是排除**：结构相似但 FedKEA 预测了其他 EC。共享折叠可以有趋同或兼职活性，FedKEA 也只是预测，所以这些候选要保留，并同时设计"目标反应"与"FedKEA 预测 EC 反应"的对照实验）
5. `USALIGN_NOT_ENZYME`
6. `USALIGN_UNVALIDATED`
7. `DEER_FALLBACK`
8. `SEQUENCE_ONLY`
9. `ANNOTATION_ONLY`

---

## Bundled lists / 附带名单

`resources/taxa/` 带两份按部位整理的微生物名单（口腔 230 种、皮肤 257 种），每条含物种、基因组装配号、位点丰度。它们**不是目标库**（没有过程、没有酶），提供的是三样目标库给不了的东西：权威物种清单、可直接下载的装配号、**实测位点丰度**。

```bash
python3 scripts/import_taxon_list.py --list resources/taxa/oral_known_microbes.tsv \
    --site oral --output-dir outputs/taxa
```

产出 `oral_taxa_registry.tsv`（丰度 → `site_presence_score`：High 5 / Medium 4 / Low 3 / Scarce 2；`No Data` 留空不当作 0 分）、`oral_genome_accessions.txt`（可直接喂 `build_gcf_list.py`）、以及带 sha256 的 provenance。皮肤名单里有 67 个 MAG/bin 号，不是 NCBI 装配号，会单独列出。

一个限制：名单只提供一项可打分证据，只填它时排名会大面积并列（口腔 230 种只有 5 个不同总分），报告会明确提示「这份排名几乎是并列的」。详见 `resources/taxa/README.md`。

## External data sources / 外部数据库

`references/gmps.md` 记录了 GMPS（Human Gut Microbial Protein Structure database，约 270 万 AlphaFold2 结构、968 个肠道细菌 + 1,255 个噬菌体基因组）的用法。它不是目标库，而是**肠道**的候选池与结构证据来源：

```bash
# 只下载需要的分卷，避免盲拉 130 GB
python3 scripts/import_gmps.py --species-map bacteria_N.tar.gz_Species.txt --taxa "Akkermansia muciniphila"
# 把 GMPS 结构检索导出接进候选表（先 dry-run 确认列映射）
python3 scripts/import_gmps.py --hits gmps_export.tsv --map "query=protein_accession,tm1=tm_score_1" --dry-run --output outputs/task/structural_candidates.gmps.tsv
```

三条边界：**只有肠道**（没有皮肤/口腔，部位维度仍由目标库负责）；**结构是 AlphaFold2 预测**，不是实验结构；**结构命中不等于功能**。导入脚本要求列映射显式声明、缺相似度指标直接拒绝、未导入的列会被点名，产物带 provenance（源文件 + sha256 + 映射 + 声明版本）。

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

四个示例按"用户手里已经有什么"排列，都改写自真实跑过的案例。每个示例给出三样东西：**可以直接发送的一句 prompt**、**Agent 实际走的链**、**一次真实运行的结果**。运行前把工具与数据路径换成你自己的。

| # | 用户手里有什么 | 起手式 | 示例 |
| --- | --- | --- | --- |
| 1 | 一个反应（底物 → 产物） | `reaction` | 鞘磷脂 → 神经酰胺 + 磷酸胆碱 |
| 2 | 一个酶名 / EC | `ec` | neutral sphingomyelinase / EC 3.1.4.12 |
| 3 | 一段参考序列 | `sequence` | DDC / P20711 |
| 4 | 只说得出关注点 | 入口 B | 皮肤外源性物质代谢 → 交棒后筛醇脱氢酶 |

### Example 1：从代谢反应出发

```text
User:
"已知代谢反应的产物为神经酰胺和磷酸胆碱，预测皮肤微生物表皮葡萄球菌
（GCF_038181645.1）是否含有相关代谢基因，并给出可以验证的实验方案。"
```

**Agent 走的链**

- `build-target-function-card` 由产物反推反应，得到 EC 3.1.4.12，写成 `target_function_card.json`
- `preflight_inputs.py` 盘点输入：候选蛋白组已给 → 直接用，不下载、不重注释
- `screen-sequence-candidates`：CD-HIT（单基因组 100%）→ DIAMOND（identity≥20 / cov≥0.7 / E≤1e-5）
- `parse_source_annotations.py` 取 `.gbff` 里的既有注释，并入候选
- 命中且注释同向 → `SEQUENCE_ANNOTATION_CONFIRMED`，**跳过结构**；最后 `summarize_candidates.py` 出交付集

**结果**（*S. epidermidis* GCF_038181645.1，2,372 个蛋白）

| 项 | 值 |
| --- | --- |
| DIAMOND 命中 | 7 条，全部指向 **WP_002468583.1** |
| 最佳比对 | 52.2% identity / 89.2% coverage / E=7.5e-107 |
| 候选自身注释 | `MULTISPECIES: sphingomyelin phosphodiesterase`（与目标同向） |
| 命中模板 | 7 条全部来自**细菌**磷脂酶 C 模板（*Bacillus cereus*、*Leptospira interrogans*、*Listeria ivanovii*）；**宿主鞘磷脂酶模板 0 条** |
| 判定 | `SEQUENCE_ANNOTATION_CONFIRMED`，结构流程跳过 |

**看点**：**宿主模板没命中，细菌模板命中**。同一个 EC 下宿主与细菌的折叠不同，用宿主酶当模板去找细菌基因会一无所获；找细菌基因要用微生物模板。

### Example 2：从已知酶 / EC 出发，多基因组

```text
User:
"预测给出的三个皮肤微生物基因组（Streptococcus pyogenes、Streptococcus thermophilus、
Staphylococcus xylosus）是否含有 neutral sphingomyelinase 相关的代谢基因，
并给出可以验证的实验方案。"
```

**Agent 走的链**

- 以 EC 3.1.4.12 建档，取 reviewed 模板（宿主 + 微生物）
- 三个基因组各自 CD-HIT（100%）→ DIAMOND；**都没有命中**
- 转结构通道：对每个基因组的候选结构直接 US-align（双向 TM≥0.5）
- `parse_fedkea.py` + `merge_candidates.py --fedkea` 验证 EC；最后打分、汇总

**结果**

| 项 | 值 |
| --- | --- |
| 序列通道 | 三个基因组 **0 命中**（放松 coverage 也一样） |
| 结构通道 | US-align 跑 1,625 / 1,744 / 2,795 个结构文件 → **2 / 3 / 1** 个候选 |
| FedKEA 升级 | *S. pyogenes* `WP_023610742.1`（TM 0.7088）、*S. thermophilus* `..._bin.19_00773`（TM 0.6988）→ `USALIGN_TARGET_EC` |
| 其余 | `USALIGN_OTHER_EC`（TM 达标，FedKEA 给的是别的 EC） |
| DEER | 未使用 |

**看点**：这一轮第一次跑时**漏了 FedKEA**，最终表因此为空。空表交付里的第一句现在就是"先查 FedKEA 跑没跑"，而不是"放宽规则集"。

### Example 3：从已知序列出发

```text
User:
"预测给定的肠道微生物青春双歧杆菌 Bifidobacterium adolescentis 是否可能编码
人类褪黑素合成的关键酶 DDC（P20711），并给出可以验证的实验方案。"
```

**Agent 走的链**

- 以 DDC / EC 4.1.1.28 / 参考序列 P20711 建档（没有 FASTA 时先给检索命令，不编序列）
- CD-HIT（100%）→ DIAMOND：**0 命中**
- 结构通道：对全部候选结构直接 US-align
- FedKEA 交叉核对，最后按 TM 排序并出实验假设

**结果**

| 项 | 值 |
| --- | --- |
| 序列通道 | **0 命中** |
| 结构通道 | 18 个候选，TM 0.60–0.71（双向），最佳模板 3RBF |
| FedKEA | 全部指向**其他 EC**（4.1.2.48、2.1.2.1、2.6.1.x、4.4.1.13、2.8.1.7） |
| 判定 | 18 条全部 `USALIGN_OTHER_EC` |

**看点**：交付**不写"无候选"**。这些是"结构相似、但预测 EC 不同"的候选，附带目标 EC 与预测 EC 并排验证的方案——同源折叠可以承载趋同或 moonlighting 活性，而 FedKEA 只是预测。

### Example 4：关注具体的生理过程，先出候选排序表，再交棒筛选

```text
User:
"我比较关注皮肤外源性物质代谢相关的生理过程，有哪些代谢酶和哪些菌值得关注呢？"
```

**Agent 走的链**

- 路由判为入口 B：只有关注点，没有 EC / 反应 / 序列
- 查库：`skin_xenobiotic` 有 6 个外源代谢类别，但全是 `starter`（无逐条证据），命中也要说明
- 库覆盖不全 → `discover_enzyme_candidates.py` 用文献补（中文题目按固定词表转成英文检索词，转不出就问用户）
- `build_candidate_shortlist.py` 合并库、文献发现、位点菌名单 → 两张推荐表（证据优先，档内按分数）

**结果：推荐候选酶**

| 排序 | 候选酶 | EC | 证据 |
| --- | --- | --- | --- |
| 1 | azoreductase (Azo1) | — | `literature_verified`（PMID 33385118） |
| 2 | β-葡萄糖醛酸苷酶 | 3.2.1.31 | `curated_prior`（PMID 26972811、36099474，肠道外推） |
| 3–6 | 环氧化物水解酶 / 4-羟基苯甲酸 1-羟化酶 / 萘 1,2-双加氧酶 / 醇脱氢酶 | — | `curated_prior`（有引用，不足以支撑皮肤 claim） |

**结果：推荐候选菌**

| 排序 | 候选菌 | 位点存在 | 代谢合理性 |
| --- | --- | --- | --- |
| 1 | *Cutibacterium acnes* | 5.000 | 4.000 |
| 2 | *Staphylococcus epidermidis* | 5.000 | 4.000 |
| 3 | *Staphylococcus aureus* | 5.000 | 3.000 |

你从表里挑一条，就用 `run_entry_b.py --select <target_id> --ec <EC> --proteome ...` 交棒给入口 A。下面的追问就是一次真实的交棒：

```text
User（接着问）:
"对 Staphylococcus epidermidis 进行醇脱氢酶的挖掘。"
```

- 这一句里只有酶**家族名**和菌名，仍然没有 EC / 反应 / 序列：家族名不是目标
- 先收敛：`alcohol dehydrogenase` 对应多个 EC，用户选定 EC 1.1.1.1
- 交棒入口 A：建档 → reviewed 模板 → CD-HIT（100%）→ DIAMOND → 并入源注释

**交棒之后的结果**（*S. epidermidis* GCF_038181645.1，2,372 个蛋白）

| 排序 | 候选蛋白 | 比对模板 | identity | coverage | E | 注释 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | WP_002438761.1 | sp\|P39451\|ADHP_ECOLI | 68.5% | 99.7% | 2.1e-161 | alcohol dehydrogenase **AdhP** |
| 2 | WP_002456130.1 | sp\|P0A9Q7\|ADHE_ECOLI | 49.3% | 95.8% | 8.9e-274 | bifunctional AdhE |
| 3 | WP_002470719.1 | sp\|P9WQB9\|ADHD_MYCTU | 39.9% | 97.8% | 9.9e-76 | zinc-dependent ADH 家族 |
| 4 | WP_002456033.1 | sp\|Q0KDL6\|ADH_CUPNH | 34.9% | 96.2% | 9.5e-62 | zinc-dependent ADH 家族 |

26 个 reviewed 模板、24 条模板-候选对齐，4 个蛋白通过快速通道；另一个 25.4% identity 的 2,3-丁二醇脱氢酶**没有**被确认（注释是另一个活性）。

**看点**：模板集若包含同种条目（*S. epidermidis* 自己的 reviewed ADH），最高命中会变成 100%——那是**同种自比对**，不是跨物种证据。看到 100% 先核对模板物种。

---

### 复现这些示例 / Reproducing them

1. `project.json` 填自己的数据路径与工具路径。
2. 目标不是 NSMase / DDC 时，改 `inputs.target_sequence_fasta`、`reference_enzyme.enzyme_name`、`reference_enzyme.ec`，或用底物/产物起动。
3. 先用 light 流程：CD-HIT + DIAMOND → 注释同向即走快速通道 → 必要时才 US-align / DEER → FedKEA → 文献证据与实验假设 → 排序。
4. 示例 4 分两段：前半段只需库 + 文献（不跑比对）就能出排序表；后半段（ADH）才需要蛋白组与比对工具。**只复现前半段是合理的终点。**
5. 每个示例的交付集都在 `outputs/task/`，用 `check_deliverables.py` 自查。

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
