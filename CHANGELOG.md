# Changelog

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
