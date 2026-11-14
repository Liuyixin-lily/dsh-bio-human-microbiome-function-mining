# 判断题清单：插件不该替你决定的事

原则：**凡是会改变"结果含义"的选择，都必须摆到用户面前**。插件可以给默认值和建议，但不能把判断悄悄做掉——那样会削弱用户自己的判断力，也让错误无法从结果里看出来。

**这些判断不是一开始全部问完**，而是走到对应步骤时才问。理由很直接：在还没筛任何东西之前问"是否启用 DEER"没有意义，用户也无法回答；那时候他只知道自己有没有文件。

每一条都对应 `environment.json` 里的 `decisions.<id>.choice`，由 `intake_environment.py --probe` 校验。

| 阶段 | 何时问 | 判断点 |
| --- | --- | --- |
| `start` | 开始之前（必须有才能动手） | `candidate_data` |
| `structure` | 走到结构分析这一步 | `candidate_structures`、`structure_source` |
| `deer` | US-align 合格候选不足时 | `deer_fallback` |
| `ranking` | 决定排序主键时 | `ranking_policy` |
| `delivery` | 写交付表时 | `delivery_rules` |

问法：

```bash
python3 scripts/intake_environment.py --ask                 # start 阶段 + 列出后面会问什么
python3 scripts/intake_environment.py --ask --at deer       # 只问 DEER 那一个
```

走到该步骤时如果还没答，脚本会**停下并打印选项**（`DECISION REQUIRED`），而不是用默认值继续：

| 脚本 | 闸门 | 未答时 |
| --- | --- | --- |
| `run_deer.py` | `deer_fallback`（`--decisions env.json`） | 退出码 3 + 打印选项；`--allow-without-usalign` 视为用户明确指示，并在输出里注明 |
| `summarize_candidates.py` | `delivery_rules`（交付表为空时） | 打印选项；`--final-rules ...OTHER_EC` 视为用户明确要收 |
| `run_usalign.py` | `candidate_structures`（结构目录为空） | 打印问句 + `blocked` checkpoint |
状态语义：`resolved`（已选且字段齐）／`needs_field`（选了没填）／`needs_decision`（还没选）／`invalid`。
**`needs_decision` 永远不等于用户同意。**

## 1. `candidate_data` — 候选数据从哪来

| 选项 | 必需字段 | 含义 |
| --- | --- | --- |
| `user_path` | `path` | 用用户自己的文件；不下载、不重注释、不覆盖 |
| `download_ncbi` | `accession`（GCF/GCA）或 `species` | 用户授权下载；**不能自己挑装配** |
| `not_available` | — | 只能建卡，不能筛选 |

## 2. `candidate_structures` — 有没有候选结构

| 选项 | 必需字段 | 含义 |
| --- | --- | --- |
| `user_path` | `dir`（建议 `kind=experimental\|predicted`） | 直接 US-align 全量 |
| `predict` | — | 先跑 structure-prediction |
| `skip` | — | 不做结构层，结论止于序列/注释 |

## 3. `structure_source` — 接受哪种结构来源

| 选项 | 含义 |
| --- | --- |
| `pdb_then_afdb` | 实验结构 > AlphaFold DB（pLDDT≥60），默认 |
| `afdb_only` | 只用 AFDB，不找实验结构 |
| `homology_ok` | 允许同源建模 |
| `de_novo` | 允许 de novo，证据最弱，必须在报告里标注 |

**为什么必须问**：预测结构不能当实验结构用；de novo 模型与实验结构的结论强度不同。

## 4. `deer_fallback` — 合格候选不足时是否启用 DEER

| 选项 | 含义 |
| --- | --- |
| `skip` | 默认不启用 |
| `run` | 需 `run_deer.py --allow-fallback` 显式放行 |

**为什么必须问**：DEER 是 fallback，不是主筛；它会把"结构检索失败"变成"另一个检索器的结果"，两者不能混为一谈。

## 5. `ranking_policy` — 最终排序主键

| 选项 | 含义 |
| --- | --- |
| `tm_first` | TM 优先（默认）；趋同/兼职酶不会被"EC 不一致"压下去 |
| `priority_first` | 严格按 tier 排序 |

**为什么必须问**：同一批候选，换主键就换结论顺序。

## 6. `delivery_rules` — 交付表收哪些 tier

| 选项 | 含义 |
| --- | --- |
| `strict` | 只收已确认（快速通道 / `USALIGN_TARGET_EC`）；交付表可能为空 |
| `include_other_ec` | 同时收 `USALIGN_OTHER_EC`（结构相似、FedKEA 预测其他 EC）作为待验证候选 |

**为什么必须问**：空交付表容易被读成"没有候选"；而把 `USALIGN_OTHER_EC` 收进来，等于承认"折叠相似值得实验验证"——这是科学判断，不是工程默认值。

## 其他需要用户判断、但已有专属入口的点

| 判断点 | 入口 |
| --- | --- |
| 目标选哪个（入口 B） | `browse_target_library.py --interactive`，不替用户挑 |
| 缺失分数是否按 0 计 | `score_target_priorities.py --allow-missing-scores` |
| 是否放宽序列阈值 | `run_diamond.py --identity/--coverage/--evalue` |
| 文献证据是否算数 | `literature_evidence.tsv` 的 `verified` 列，只认 `yes` |
| BSL 等级与外包范围 | `build_cro_work_order.py --bsl/--scope/--bsl-note` |
