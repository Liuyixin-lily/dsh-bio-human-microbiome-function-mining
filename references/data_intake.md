# 数据入口：两个必须先问清的问题

跑任何筛选之前，有两件事**必须问用户**，不能替他判断。这两件事各自都有一个代码闸门，闸门不是建议，是硬约束。

## 两个决策点是**选择题**，记录在 `environment.json`

```json
{
  "decisions": {
    "candidate_data":        {"choice": "user_path", "path": "/abs/x.faa", "annotation_path": "/abs/x.gbff"},
    "candidate_structures":  {"choice": "user_path", "dir": "/abs/pdb", "kind": "experimental"}
  }
}
```

可选项（`scripts/intake_environment.py --ask` 会原样打给用户）：

| 决策 | 选项 | 必需字段 | 含义 |
| --- | --- | --- | --- |
| `candidate_data` | `user_path` | `path` | 用用户自己的文件 |
| | `download_ncbi` | `accession`（GCF/GCA）或 `species` | 用户授权下载 |
| | `not_available` | — | 只能建卡，不能筛选 |
| `candidate_structures` | `user_path` | `dir`（建议 `kind=experimental\|predicted`） | 直接 US-align |
| | `predict` | — | 先跑 structure-prediction |
| | `skip` | — | 不做结构层，结论止于序列/注释 |

`--probe` 会逐项校验并报状态：`resolved` / `needs_field`（选了但没填）/ `needs_decision`（还没选）/ `invalid`。
**`needs_decision` 永远不等于"用户同意"。**

## 必问 1：候选数据在哪

```
候选菌的蛋白组（.faa）或基因组（.fna/.gbff）的绝对路径？
有没有对应的注释文件（.gbff/.gff）？
```

- 用户说**有** → 直接用它，不下载、不重注释、不覆盖。
- 用户说**没有** → 问"要我从 NCBI 下载吗？给 GCF/GCA 号或物种名"。
- **绝不自己挑一个装配。** 示例 3 里我跳过这一步，自己去 UniProt 查了个参考蛋白组顶上去，用户真正要用的却是另一个 GCF——这类替代无法从结果里看出来，属于不可接受的隐蔽错误。

闸门：

```bash
python3 scripts/preflight_inputs.py --project project.json --require-candidate-data
```

没有候选序列时退出码 1，并打印要发给用户的问句。

## 必问 2：有没有候选菌的结构文件

```
有：结构目录的绝对路径（PDB/mmCIF），是实验结构还是预测结构？
没有：是否先跑 structure-prediction（PDB > AlphaFold DB pLDDT≥60 > 同源建模 > de novo）？
```

- 用户说**有** → 直接 US-align 全量。
- 用户说**没有** → 先确认是否预测，再动手；不要静默跳过结构层，也不要静默开始预测。
- 两个默认都不安全：跳过会让"结构支持"缺失，预测会改变结果的含义（预测结构 vs 实验结构）。

闸门（两层）：

```bash
python3 scripts/preflight_inputs.py --project project.json --require-candidate-structures
python3 scripts/run_usalign.py --target <template.pdb> --candidate-dir <dir> --outdir <out>
# 目录为空时：打印问句 + 写 status=blocked 的 checkpoint，不跑、不跳过
```

## 为什么必须问，而不是"先跑起来再说"

| 自己判断 | 后果 |
|---|---|
| 替用户下载一个蛋白组 | 用的是**别的装配**，结果无法与用户的数据对齐，且看不出来 |
| 假定"没有结构"就跳过结构层 | 结构支持缺失，tier 停在 `SEQUENCE_ONLY`，看起来像"没有候选" |
| 假定"可以预测"就直接预测 | 证据从实验结构变成预测结构，结论强度变了但报告里未必体现 |

## 顺序

```
【0】问候选数据路径        ← 必问 1
【0】问结构文件路径/是否预测  ← 必问 2
【1】模板序列 + 结构（宿主 + 微生物，reviewed）
【2】CD-HIT → DIAMOND → 注释 → 快速通道
【3】结构层（若快速通道未成立）
```

两个问题都可以在 `scripts/intake_environment.py --ask` 的「数据路径」组里看到，那里写明了用户回答"没有"时该继续问什么。
