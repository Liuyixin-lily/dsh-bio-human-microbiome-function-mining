# GMPS: Human Gut Microbial Protein Structure database

外部数据库。**它不是目标库**，而是肠道微生物的结构蛋白组数据集 + 结构检索服务，在本插件里作为**候选池与结构证据来源**使用。

## 它是什么（已核实）

| 项 | 内容 |
| --- | --- |
| 全称 | Human Gut Microbial Protein Structure database（GMPS） |
| 规模 | 约 270 万个 AlphaFold2 预测结构；968 个肠道细菌基因组 + 1,255 个噬菌体/前噬菌体基因组（209 phage + 1,046 prophage） |
| 每条目带什么 | 结构文件、蛋白序列、功能注释（DRAM v1.3 / microbeannotator v2.0.5 / eggnog-mapper v2.1.9）、基因组文件，**按物种分卷打包** |
| 建模与检索方法 | AlphaFold2、MODELLER 9.8、US-align |
| 数据存档 | Dryad，DOI [10.5061/dryad.gtht76hx2](https://doi.org/10.5061/dryad.gtht76hx2) |
| 代码 | GitHub [BinhongLiu/GMPS](https://github.com/BinhongLiu/GMPS/tree/GMPS_v1)；Zenodo DOI [10.5281/zenodo.17518517](https://doi.org/10.5281/zenodo.17518517)（MIT） |
| 网站 | <https://www.gmpsdb.cn/home>，提供「提交模板结构比对」与「按物种下载」 |
| 论文 | Cell Host & Microbe（2025）*Exploring functional insights into the human gut microbiome via the structural proteome* |

体量：细菌部分压缩约 130 GB、解压约 1.3 TB，分 8 卷（`bacteria_1..8.tar.gz`）；噬菌体 0.75 GB、前噬菌体 2.3 GB；**`bacteria_final_annotation.zip` 只有 250 MB**，通常先取它。

## 在本插件里的三个位置

| 位置 | 怎么用 |
| --- | --- |
| **候选池**（替代或补充 `genome-search` → `genome-download` → `genome-annotation` → `structure-prediction`） | 直接拿 GMPS 的序列/结构/注释，省掉自己注释和 AlphaFold 预测。`--species-map` 先定位只需下载哪几卷 |
| **结构检索的预计算替代** | GMPS 的 Search 是「提交模板结构 → 比对结构化蛋白组」。对小规模问题可以先用它粗筛，再用本地 US-align/DEER 复核 |
| **独立注释证据层** | DRAM / microbeannotator / eggnog 三套注释可作为 `source_feature_annotations.tsv` 的另一条证据链 |

## 命令

```bash
# 1. 只下载需要的分卷（避免盲拉 130 GB）
python3 scripts/import_gmps.py --species-map bacteria_N.tar.gz_Species.txt \
    --taxa "Akkermansia muciniphila,Faecalibacterium prausnitzii"

# 2. 把 GMPS 结构检索的导出结果接进候选表（先 dry-run 看列映射）
python3 scripts/import_gmps.py --hits gmps_export.tsv \
    --map "query=protein_accession,species=organism_or_strain,tm1=tm_score_1,tm2=tm_score_2,plddt=plddt_mean" \
    --tool-version "GMPS_v1 (2026-11 export)" --dry-run \
    --output outputs/task/structural_candidates.gmps.tsv

# 3. 把注释表接进注释证据层
python3 scripts/import_gmps.py --annotation bacteria_final_annotation.tsv \
    --map "protein=protein_accession,product=product,ec=ec_number" \
    --annotation-source DRAM --source-file bacteria_final_annotation.tsv \
    --output outputs/task/source_feature_annotations.gmps.tsv
```

产物直接符合本插件既有 schema（`structural_candidates.schema.tsv`、`source_feature_annotations.schema.tsv`），可以并入 `merge_candidates.py`。

## 三条硬边界

1. **只有肠道。** 968 个细菌基因组 + 噬菌体，没有皮肤、口腔、阴道。它对"部位"这个维度没有任何帮助——那正是目标库存在的原因。
2. **结构是预测，不是实验。** AlphaFold2 模型，且是 2.7M 规模，不能当实验结构引用。`plddt_mean` 只在 AlphaFold 模型上有意义。
3. **结构命中 ≠ 功能。** 与本插件一贯的立场一致：结构相似度只提出问题，功能要靠酶活与文献。导入脚本不会写任何功能结论。

## 导入时的诚实性规则

- **列含义靠 `--map` 显式声明。** 我的别名表刻意保守（`query` / `target` 这类歧义名不自动映射，因为不知道 GMPS 导出把它们用作模板还是命中蛋白）。必需字段无法确定时**报错退出**，不猜。
- **没有相似度指标就拒绝。** 导出里找不到 TM-score 列时报错，不会把任意 `score` 当 TM。
- **空闲列会被点名。** 没被导入的列列在 warnings 里，避免静默丢信息。
- **每个产物带 provenance sidecar**：源文件、sha256、行数、列映射、声明的版本、阈值与警告。
- **`structure_support` 按双向 TM 策略计算**（TM1 与 TM2 均 ≥ 0.5），只有单向 TM 时留空，不臆断。
