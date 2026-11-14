# Per-site microbe lists

Two curated taxon lists, one per body site. **They are not a target library**: they
carry a taxon name, a genome id and a site-abundance label — no physiological process
and no enzyme. What they give the plugin is the three things the library lacks:

| 用途 | 怎么用 |
| --- | --- |
| 每个位点的权威物种清单 | 替代手写的 `focus_taxa` |
| 具体基因组装配号 | 直接选候选基因组，不用关键词搜索 |
| **实测位点丰度** | `site_presence_score` 有了数据来源，不再是主观打分 |

## 文件

| 文件 | 行数 | 物种 | 属 | 装配号 | 丰度 |
| --- | --- | --- | --- | --- | --- |
| `oral_known_microbes.tsv` | 230 | 230 | 70 | 215 GCF + 15 GCA | High 62 / Medium 95 / Low 20 / Scarce 47 / No Data 4 / 空 2 |
| `skin_known_microbes.tsv` | 257 | 257 | 76 | 178 GCF + 12 GCA + **67 MAG/bin** | Scarce 206 / Low 24 / High 14 / Medium 13 |

两份都已核对：物种名全是标准二名法，无重复。

**注意皮肤名单的偏斜**：257 个物种里 206 个是 *Scarce*——这是一份"已知皮肤微生物"普查名单，不是"优势菌"名单。用它做 `site_presence` 时，高频菌自然会排到前面，但别把 Scarce 理解成"不重要"。

## GMPS：同一套格式的第三份名单（肠道）

`gmps_download_manifest.csv` 来自 GMPS 代码仓库（[BinhongLiu/GMPS](https://github.com/BinhongLiu/GMPS/tree/GMPS_v1)，MIT）的 `wget_links_download.csv`，取回日期 2026-11-14，sha256 前缀 `3e5399ef`。

| 项 | 内容 |
| --- | --- |
| 行数 | 1,189（Bacteria 968 / Prophage 176 / Phage 42 / All 3） |
| 唯一物种 | 1,047 |
| 列 | `Index`, `Bacteria/Host species`, `Download link` |
| **装配号** | **没有** —— GMPS 是按物种打包，不是按 GCF/GCA |
| 下载方式 | 每行一条 `wget https://gmpsdb.cn/api/download/<类型>/<id>/download/ -O <文件名>` |

所以它回答你的问题：**能出物种名单，出不了 GCF/GCA 清单。**

```bash
python3 scripts/import_taxon_list.py --list resources/taxa/gmps_download_manifest.csv \
    --site gut --output-dir outputs/taxa            # 先加 --inspect 看列
```

产出：
- `gut_taxa_registry.tsv` — 1,047 个物种；**`site_presence_score` 全空**（没有丰度列，按规则不当作 0 分）
- `gut_download_manifest.tsv` — 1,189 条 `物种 / url / 归档文件名`
- `gut_genome_accessions.txt` — 空文件（没有装配号）

那 GCF/GCA 到底能不能拿到？`GMPS_genomes_metadata.zip`（197 KB）的字段我**没能验证**：Dryad 那份是同行评审私有分享，脚本取回被 403 挡住。如果确实要装配号，两条路：

1. 手动从 <https://www.gmpsdb.cn/home> 或 Dryad 分享页下载 metadata，`--inspect` 看有没有 accession 列，再用 `--genome-col` 指过去；
2. 直接用物种名走 `genome-search`（`--source gut`）反查 GCF/GCA —— 这是插件已有的能力，不依赖 GMPS。

## 来源与责任

- 这两份名单由用户提供（2026-11-14），字段结构类似 HOMD / 人体微生物组参考库的导出。
- sha256 见导入时生成的 provenance（`<site>_taxa_list.provenance.json`）。
- **再分发责任**：仓库里保留了原始文件便于复现。如果上游数据许可不允许随插件分发，删掉这两份、改用用户自备的同格式文件即可，导入脚本不依赖固定路径。
- 不在这里附任何 PMID/DOI：名单本身不带引用，不能凭空补。

## 用法

```bash
# 1. 名单 -> 排序器需要的表 + 装配号清单 + provenance
python3 scripts/import_taxon_list.py \
    --list resources/taxa/oral_known_microbes.tsv --site oral \
    --output-dir outputs/taxa

# 产出：
#   outputs/taxa/oral_taxa_registry.tsv        物种 + 位点丰度打分（High 5 / Medium 4 / Low 3 / Scarce 2）
#   outputs/taxa/oral_genome_accessions.txt    一列 GCF/GCA，可直接给 genome-download
#   outputs/taxa/oral_unresolved_ids.tsv       MAG/bin 等非 NCBI 号（有则）
#   outputs/taxa/oral_taxa_list.provenance.json 源文件 + sha256 + 计数 + 映射规则

# 2. 拿装配号去下载基因组（不用再按关键词搜）
#    这批是"已知 GCF/GCA 清单"，用 --manual 而不是 --species
python3 skills/genome-download/scripts/build_gcf_list.py \
    --manual outputs/taxa/oral_genome_accessions.txt --out work/gcf_list.tsv
python3 skills/genome-download/scripts/build_download_links.py \
    --gcf work/gcf_list.tsv --out work/urls.txt
python3 skills/genome-download/scripts/download_genomes.py \
    --metadata work/gcf_list.tsv --urls work/urls.txt --out work/genomes

# 3. 和其它证据一起排序
python3 scripts/score_target_priorities.py \
    --taxa outputs/taxa/oral_taxa_registry.tsv \
    --genomes work/genome_search/oral.tsv \
    --auto-score --site oral --output outputs/task/priorities
```

## 丰度映射（写死，可复核）

```
High = 5    Medium = 4    Low = 3    Scarce = 2
No Data / unknown / 空 = 留空
```

`No Data` 和空值**不当作 1 分**——没人测过不等于不存在。这类行会作为缺口保留，需要你补证据。

## 一个必须知道的限制

这两个名单只提供**一项**可打分证据（位点丰度）。只填这一项时，`score_target_priorities.py` 的排名会大面积并列：口腔 230 个物种只有 5 个不同总分，皮肤同理。报告里会出现「这份排名几乎是并列的」的提示。

补齐方式：`--genomes`（基因组可得性）、`--literature`（文献证据）、`--library`（生化清晰度等），或人工填剩余分项。**在补齐之前，不要把这份顺序当成结论。**
