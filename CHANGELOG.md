# Changelog

## [2.1.0](https://github.com/bbpfish/smart-memory/compare/v2.0.0...v2.1.0) (2026-07-01)


### Features

* add ClawdHub publish sync to prompt adaptive (Step 12.4); fix: Step 1 data source from signals.jsonl back to messages table ([b0f3fca](https://github.com/bbpfish/smart-memory/commit/b0f3fcac4350d7170f87232d35dfbb13dbf775a7))
* add harvest-structured (Method 1 LLM preprocessing) ([3a2a637](https://github.com/bbpfish/smart-memory/commit/3a2a63743f672f2bdf1f393cb3d4acbaca0ee7b7))
* add recalc-decay command for batch Ebbinghaus retention + importance update ([b49d5aa](https://github.com/bbpfish/smart-memory/commit/b49d5aa8b7500cd48133c8af8c25f874e53ca377))
* decay-report baseline 对比机制，修复遗忘曲线巡检失效 ([1bbfa5a](https://github.com/bbpfish/smart-memory/commit/1bbfa5a54b5e907817c09c3af57212259e745fbc))
* Step 1 增加方法3质量门——harvest 前逐卡片自审，淘汰非通用知识 ([c969faf](https://github.com/bbpfish/smart-memory/commit/c969faf8d186ff1e247161746658a3db7211906b))
* upgrade nightly maintenance to self-evolving engineer (7-&gt;13 steps) ([5b85c98](https://github.com/bbpfish/smart-memory/commit/5b85c98b30c3a8f0225a8d5477ae1a5e4218bbc1))
* 同步夜间巡检示例模板上下文管理 + checkpoint 机制 (v2.3.3) ([4354f15](https://github.com/bbpfish/smart-memory/commit/4354f15e55b7bdcec95bf2ec23e962234983cd0f))


### Bug Fixes

* atomic JSON writes to prevent index.json corruption from concurrent read/write ([88e2f43](https://github.com/bbpfish/smart-memory/commit/88e2f4308f2eb960f6916cb5ab7854d70de2794d))
* auto-compact + tag normalization ([cbed3dd](https://github.com/bbpfish/smart-memory/commit/cbed3ddd0f37a09c44a0feb6ecabd033beab92f9))
* auto-rebuild index on corruption, remove silent errors=replace (v2.3.4) ([34bbf64](https://github.com/bbpfish/smart-memory/commit/34bbf640ebd343db9c32996c1dc74a16bbf427f8))
* **nightly-maintenance:** Step1 data.db-&gt;signals.jsonl + Step10.3 auto-compact after recalc-decay ([b4b3786](https://github.com/bbpfish/smart-memory/commit/b4b3786d8aa33b18567762eedcbb4dd45dd9a9e3))


### Performance Improvements

* remove redundant tokens field from TF-IDF index (40% size reduction) ([a3096d4](https://github.com/bbpfish/smart-memory/commit/a3096d4a837485af83dc4c4b8c55b134cce578e4))

## [2.0.1] - 2026-07-01

### Fixes
- 移除 v2.0.0 中声明的 P4 知识图谱 feature（graph-build/check/full/stats/health）；该特性从未实现，graph.json 为幻影文件
- CHANGELOG 中对应的 516 节点 / 1156 边 数据声明已撤回

### Features
- 新增 `check-index` 命令：检查索引健康状态（年龄 > 30 天 / 卡片数 +20% 阈值）
- `build-index --auto`：仅在检测到退化时重建，否则跳过
- 索引元数据持久化至 `knowledge/index_meta.json`，追踪构建时间与卡片快照

## [2.0.0] - 2026-07-01

### Features
- 向量语义检索：ONNX 多语言 MiniLM 向量索引，支持 tfidf/vector/hybrid 三种模式
- Session 管理：session 创建/列表/切换，多会话隔离
- 夜间巡检全流水线：harvest → dedup → synthesize → cross-link → signal-analysis → build-index
- 重要性自动计算：基于 reinforced_count + weight + retention 信号

### CLI 扩展
- 命令数从 8 增至 16 个（含新增 check-index）

### Performance
- batch_mode signal、mtime 缓存、O(1) 查找、条件触发巡检
- 索引体积: TF-IDF + 向量索引
