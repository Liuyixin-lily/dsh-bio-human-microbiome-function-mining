# Target library / 目标库

## 这个库是必需的还是可选的

**可选的。** 删掉 `library/` 里的全部内容，插件仍然能做完所有功能——只是少了「先看哪几个酶」这份菜单。代价是明确可数的：

| 能力 | 有库 | 没有库 |
| --- | --- | --- |
| 入口 B（凭兴趣挑目标） | 有菜单可挑 | 无，只能走入口 A（给出 EC / 反应 / 序列） |
| `--auto-score` 自动分项 | 8 项自动（库 3 + 参考酶 1 + genome-search 2 + 文献 2） | 4 项自动（genome-search 2 + 文献 2），另外 3 项退回人工/缺口 |
| 按部位挑基因组、序列/结构/注释/文献、排序、外包工作单 | 一样 | 一样 |

空库是被支持的状态，不是错误：

```bash
python3 scripts/browse_target_library.py --library-dir /tmp/empty --list-domains
# 目标库为空（/tmp/empty）。这不是错误——库只是可选的「菜单」。
```

路由脚本也会区分两种"没有命中"：`library: not configured`（没配库）与 `library: MISS at this site`（配了库但这个部位没覆盖）。

## 一个条目要「能用」需要什么

`--require-evidence` 把这件事变成可执行的门槛：只有 `evidence_status: literature_verified`
且 `evidence_refs` 非空的条目才进入菜单。用这个标准衡量，当前随插件提供的库是：

```bash
python3 scripts/browse_target_library.py --require-evidence --list-domains
# gut   0 processes, 0 enzyme targets
# skin  0 processes, 0 enzyme targets
# 已隔离 27 个条目
```

**27 条全部被隔离，可用条目为 0。** 这不是 bug，是诚实的度量：库里的内容都是
`curated_prior`，一条引用也没有。

一个真正"能用"的条目应该长这样（每格都必须有来源）：

| 字段 | 内容 | 必须来自 |
| --- | --- | --- |
| 用户会怎么问 | 口语关键词（油脂分泌 / 出油 / 油性皮肤） | 用户语言，可以是策展 |
| 这个部位有什么生理过程 | 过程名 + 一句话说明 | 综述/教科书，**带引用** |
| 过程 → 酶 | 酶名 + EC + 反应式 | IUBMB / Rhea / BRENDA（可自动查，不靠记忆） |
| 哪些菌带这个酶 | 物种 + 依据 | 文献（verified）或你自己的基因组筛查结果 |
| 是否暗物质 | `dark_matter` | 由"有无 EC + 有无已表征代表酶"判定，不由印象判定 |
| 值不值得先做 | 优先级/评分 | 排序器（`score_target_priorities.py --auto-score`），不写死在库里 |
| 怎么验证 | 可证伪实验 | 由目标反应决定 |
| 证据 | `evidence_refs` | 真实 PMID/DOI。没有就不要声称有 |

结论：**库里的"知识"部分必须来自检索，不能被写入。** 库能长期提供的是结构（三层索引）、
命名与 EC 词汇、以及给排序器的输入事实——这些不靠记忆也成立。

## 为什么只有两个部位

必须先说清楚：`skin.json` 和 `gut.json` 是**示例参考域**（`role: shipped_example`），不是人体微生物组的覆盖范围。

它们之所以是这两个部位，没有覆盖性论证——皮肤来自最初的"表皮葡萄球菌是否有神经酰胺/磷酸胆碱相关酶"问题，肠道来自已有的肠道工作。换句话说，这反映的是一个课题组的调研范围，不是一个人体微生物组靶点全集。

**插件能做的人体部位远多于两个。** 按部位做的能力是通用的：

| 环节 | 是否受库限制 |
| --- | --- |
| 目标建档（EC / 反应 / 序列） | 不受限，任何部位都行 |
| 按部位挑基因组（genome-search） | 不受限，内置 skin / oral / gut / respiratory / urogenital / blood / environment |
| 序列、结构、注释、文献证据 | 不受限 |
| **"这个部位有哪些酶值得筛"的菜单** | **受库限制** |

所以库只是一份**菜单**，不是能力边界。三种情况分开处理：

1. **用户能说出目标** → 走入口 A，`library/` 完全不参与。
2. **用户知道部位、说不出目标** → 库没覆盖时不要硬编，先用 `resolve_target_intent.py` 把问题route到文献检索与收敛步骤；或者先用 `genome-search --source <部位>` 把该部位的基因组和注释拿到手，再在有真实序列的基础上选靶点。
3. **用户要长期在这个部位工作** → 用 `build_library_domain.py` 生成一个 `role: user_defined` 的域。生成域必须 `content_status: starter`，每个酶的 `evidence_refs` 强制为空，写盘前要过真实校验。

如果你希望库里出现更多部位，正确做法不是让我凭记忆补条目，而是先跑 `literature-evidence` 把该部位的关键酶查实，再用 spec 生成——这样条目带 `provenance_source`，而不是"看起来像真的"。

---

这是一个**可浏览、可搜索、可选择**的靶点库，用来把用户模糊的自然语言兴趣变成可执行的筛选目标。

> 它是**可选入口**，不是必经步骤。用户已经能说出酶名 / EC 号 / 底物-产物反应 / 一段序列时，直接走 `build-target-function-card` 建卡片，不要绕到这里。只有在用户说不出目标、只知道关注什么的时候才用库。

```
domain（身体部位 / 生态位）
  └── process（用户关心的生理过程，例如「油脂分泌」「体味」）
        └── enzyme（真正拿去筛的酶目标，带 EC、反应、起手式、验证实验）
```

用户的话术与库的层级是错位的：用户说“皮肤代谢有哪些重要的过程”，回答的是 `process` 列表；用户说“我关注油脂分泌”，落到 `skin_sebum_lipolysis`；用户说“哪些酶值得看”，落到这一 process 下的 `enzyme`。库的作用就是把这三层逐级摊开给用户挑，而不是让用户自己先想好酶名或 EC 号。

## 文件

| 文件 | 内容 | role |
| --- | --- | --- |
| `skin.json` | 皮肤，10 个 process / 19 个酶目标 | `shipped_example` |
| `gut.json` | 肠道，5 个 process / 8 个酶目标 | `shipped_example` |
| 你自己生成的 `<site>.json` | 任意部位 | `user_defined`（由生成器自动写入） |
| `../schemas/target_library.schema.json` | 库文件的 JSON Schema 契约 |

`starter` 表示“只覆盖最常被问到的几条轴，别当完整清单用”。新增身体部位就新增一个 `<domain>.json`，不需要改代码。

## 命令

```bash
# 有哪些身体部位
python3 scripts/browse_target_library.py --list-domains

# 皮肤域有哪些生理过程（含每个过程下的酶目标）
python3 scripts/browse_target_library.py --list-processes skin

# 有哪些值得关注的菌（带角色说明和它驱动哪些过程）
python3 scripts/browse_target_library.py --list-taxa skin

# 自然语言关键词搜索（中英文都行，整句也可以）
python3 scripts/browse_target_library.py --search "油脂分泌"
python3 scripts/browse_target_library.py --search "我关注油脂分泌"
python3 scripts/browse_target_library.py --search "skin barrier"

# 展开一个 process 或 enzyme
python3 scripts/browse_target_library.py --show skin_thioalcohol_odour

# 菜单式选择：domain -> process -> enzyme，最后写卡片
python3 scripts/browse_target_library.py --interactive --output-dir outputs/task

# 直接导出某一目标的卡片（非交互）
python3 scripts/browse_target_library.py --export-card skin_sphingomyelin_phosphodiesterase --output-dir outputs/task

# 把整库摊平成一张表交给 Excel / 用户勾选
python3 scripts/browse_target_library.py --export-tsv outputs/task/target_library.tsv

# 审计库内容本身
python3 scripts/browse_target_library.py --validate
```

`--export-card` 会写两个文件：

- `target_function_card.json` — 下游流程直接消费，`input_source` 记为 `library`，并带上 `library_id` / `library_version`。
- `target_selection.md` — 给人看的选型记录：为什么做这个过程、关键菌、推荐起手式、证据状态、可证伪的验证实验。

## 内容规则（必须遵守）

这些规则不是格式洁癖，而是防止“库里看着权威、实际是编的”。

1. **EC 号只写你确定存在的。** 完整号用 `ec_confidence: full`，只知道家族就用 `3.1.1.-` 记 `family`，**没有 EC 号就留空并记 `none`**。不要为了整齐去套一个相近酶的 EC 号 —— 这正是库里那些 `dark_matter: true` 条目要表达的事。
2. **不填 `evidence_refs`。** 库是策展先验（`evidence_status: curated_prior`）。只有 `literature-evidence` 真实检索到结果后，才能把 PMID/DOI 写进 `evidence_refs` 并把状态升到 `literature_verified`；`--validate` 会拒绝空引用的 `literature_verified`，也会拒绝格式不像 PMID/DOI 的引用。
3. **`provenance_note_zh` 要写清这条目靠什么。** 例如“EC 号取自 IUBMB 酶命名，不是文献引用”，或者“具体基因符号刻意留空，需文献核实后填写”。
4. **不要凭记忆写 UniProt / PDB / 基因符号。** 需要参考酶集合时用 `scripts/fetch_reference_enzymes.py --ec <EC>` 现场查，让脚本返回真实登录号。
5. **`validation_note_zh` 必须是可证伪的实验**，写清底物、读出和对照组；不要写“测一下酶活”这种没有判据的话。
6. **`dark_matter: true`** 用于“活性真实存在、但没有 EC 号或没有已表征的代表酶”的条目。这类目标只能按序列 / 结构起手，`entry_point` 相应设为 `sequence`。

## 库里没有的方向

库覆盖有限（`skin` + `gut`），但「没覆盖」不等于「做不了」。标准升级路径：

```bash
# 1. 先让路由脚本判断这个问题属于哪种形状
python3 scripts/resolve_target_intent.py --query "口腔牙周炎相关菌有哪些酶值得看"

# 2. 如果用户其实能说出目标，直接建档，不需要扩库
python3 scripts/build_target_function_card.py --output outputs/task/target_function_card.json --ec 3.5.1.23

# 3. 如果要长期在这个部位上工作：spec -> 生成 starter 域
python3 scripts/build_library_domain.py --init --domain oral --output specs/oral.json
python3 scripts/build_library_domain.py --build --spec specs/oral.json --output library/oral.json
python3 scripts/browse_target_library.py --validate
```

`build_library_domain.py` 把诚实性写进了代码，而不是靠人自觉：

- 空字段 = 构建失败，脚本不填占位符；
- 生成的文件**只能是** `content_status: starter`，不允许自称 `curated`；
- 每个酶强制 `evidence_status: curated_prior`、`evidence_refs: []`；
- 每个酶必须写 `provenance_source`（`iubmb_enzyme` / `rhea` / `uniprot` / `user_supplied` …）；
- 写盘前跑真正的库校验，校验不过就不写。

生成的文件带 `domain.expansion.method: generated_from_spec`，读者一眼能看出它是机械生成的。校验器会拒绝把生成域改成 `curated`。

## 新增一个 process

在对应 `<domain>.json` 的 `domain.processes` 里加一条，`--validate` 会检查：

- 必填字段齐全，`id` 为 snake_case；
- `keywords_zh` / `keywords_en` 非空（用户就是靠这些词搜进来的）；
- `key_taxa` 里每个物种都在 `domain.focus_taxa` 出现过；
- 至少有一个 enzyme（没有目标的 process 选不了，等于死条目）；
- 每个 enzyme 的 EC / `ec_confidence` / `entry_point` / `evidence_status` 自洽；
- 全局 `domain.id` / `process.id` / `enzyme.id` 不重复。

## 边界

- 库**不是**文献证据。它回答“值不值得筛”，不回答“已经证明有”。
- 库**不是必经入口**。它是入口 B；入口 A 是用户直接给出目标、由
  `build-target-function-card` 建档，两条路在 `target_function_card.json` 汇合。
- 库没有命中，不代表功能不存在，只代表尚未策展；此时应回到 `build-target-function-card` 按用户给的目标酶 / EC / 反应显式建档。
- 库是人体微生物组功能域的索引，不含宿主自身酶作为筛选目标（宿主酶只作为 `host_context_zh` 出现）。
