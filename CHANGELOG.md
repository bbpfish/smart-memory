# Changelog

## [2.0.0] - 2026-07-01

### Features
- P4 知识图谱：Property Graph 构建、图健康检查、图统计、全量重建
- 向量语义检索：ONNX 多语言 MiniLM 向量索引，支持 tfidf/vector/hybrid 三种模式
- Session 管理：session 创建/列表/切换，多会话隔离
- 夜间巡检全流水线：harvest → dedup → synthesize → cross-link → signal-analysis → build-index
- 重要性自动计算：基于 reinforced_count + weight + retention 信号

### CLI 扩展
- 命令数从 8 增至 15 个：signal、session、session-list、recalc-importance、graph-build/check/full/stats/health

### Performance
- batch_mode signal、mtime 缓存、O(1) 查找、条件触发巡检
- 索引从 225KB 扩至 970KB (TF-IDF) + 279KB (向量)
- 知识图谱 516 节点 / 1156 边
