---
name: smart-memory
version: 1.0.0
description: 分层长期记忆管理系统：任务前自动 TF-IDF 召回相关记忆，任务后持久化知识卡片，支持语义去重、时间衰减权重、全量索引重建，可从 self-learning-skills 一键迁移历史数据。
---

# 分层长期记忆管理

任务前自动从知识库召回相关历史经验，任务后持久化新知识卡片。

## 1) 核心命令

脚本入口：`python skills/market/smart-memory/scripts/memory.py <command>`

| 命令 | 用途 |
|------|------|
| `recall -q "关键词" --top 8 --days 30` | 召回相关记忆，注入当前上下文 |
| `record --title ... --when ... --problem ... --solution ... --tags ...` | 记录知识卡片，自动去重 |
| `harvest --text "摘要" --auto-confirm` | 从对话摘要自动提取并写入知识卡片 |
| `review --days 30 --query "关键词"` | 回顾指定时间范围的记忆 |
| `build-index` | 全量重建 TF-IDF 索引 |
| `migrate` | 从 self-learning-skills 迁移历史数据 |
| `dedup --threshold 0.45` | 语义相似度去重检测 |

## 2) 存储结构

根目录：`D:\hi\.agents\memory\smart-memory\v1\users\hi\`

| 文件 | 说明 |
|------|------|
| `knowledge/cards.jsonl` | 知识卡片数据（权重、状态、时间戳） |
| `knowledge/index.json` | TF-IDF 索引 |
| `signals.jsonl` | 使用信号（recall/reinforced/used） |
| `recommendations.jsonl` | 改进建议记录 |

## 3) 工作流（强制执行）

| 触发 | 动作 |
|------|------|
| 对话开始 | `recall -q "用户消息关键词" --top 8 --days 30` |
| 任务完成且有可复用经验 | 立即 `record`，交付即沉淀，不等用户确认 |
| 索引退化（30天 / 卡片+20%） | `build-index` 重建索引 |

可复用经验判定：通用规律、配置用法/陷阱、有效操作模式、技能改进点。纯粹查询/只读不算。

## 4) 性能概况

| 指标 | 当前值 | 警戒线 | 对策 |
|------|--------|--------|------|
| recall 耗时 | ~170ms | >500ms | `build-index` |
| 索引体积 | 225KB | >1MB | 归档废弃卡片后 rebuild |
| 上下文注入 | ~8KB (12条) | >20KB | 降低 `--top` 到 5-6 |
| 卡片总数 | 64 条 | >500 | `dedup` 合并相似 |
