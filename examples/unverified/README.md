# Unverified reference content / 未核实的参考内容

这里的文件**不会**被默认加载。`library/` 才是插件默认读取的目录。

## 里面是什么

- `skin.full.json` — 皮肤域 v1.0.0：10 个生理过程 / 19 个酶目标
- `gut.full.json` — 肠道域 v1.0.0：5 个生理过程 / 8 个酶目标

这些条目都是 `evidence_status: curated_prior`、`evidence_refs` 为空——即**没有文献引用的策展先验**。它们作为"靶点可以怎么组织"的参考仍然有用，但**不能作为证据使用**。

## 为什么搬出来

`library/` 现在只放**逐条有已验证 PMID** 的条目。用 `--require-evidence` 门槛衡量：

```bash
python3 scripts/browse_target_library.py --library-dir examples/unverified --require-evidence --list-domains
# skin  0 processes, 0 enzyme targets
# gut   0 processes, 0 enzyme targets
# 已隔离 27 个条目
```

27 条全部不达标。与其把它们摆在默认菜单里让人误以为有据，不如放到这里、显式说明。

## 什么时候会用

- 想看看"一个域可以包含哪些过程"的写法 → 直接读 JSON。
- 想从中挑一条来补证据 → 跑 `literature-evidence` 拿到真实 PMID/DOI，把 `evidence_status` 升为 `literature_verified`、写入 `evidence_refs`，再挪进 `library/`。
- 想对比/回归测试 → `--library-dir examples/unverified`。

```bash
# 只读查看，不进入默认库
python3 scripts/browse_target_library.py --library-dir examples/unverified --list-processes skin
```

## 边界

这些条目里的 EC 号取自 IUBMB 命名（可信），但"哪个菌带这个酶""它在皮肤上有多重要""值不值得先做"都是没有引用支撑的判断。搬运时请只把 EC 与反应式当事实，其余一律当作待验证假设。
