---
name: smart-memory
version: 1.0.0
description: 分层长期记忆管理系统：任务前自动 TF-IDF 召回相关记忆，任务后持久化知识卡片，支持语义去重、时间衰减权重、全量索引重建，可从 self-learning-skills 一键迁移历史数据。
---



# 分层长期记忆管理

任务前自动从知识库召回相关历史经验，任务后持久化新知识卡片。实现记忆的半主动化推送。

---

## 1) 核心能力

| 功能 | 说明 |
|------|------|
| 记忆召回 | 任务前根据用户需求在知识库中 TF-IDF 检索，将 Top-K 相关记忆注入当前上下文 |
| 记忆记录 | 任务后将可复用经验持久化为知识卡片，含时间戳和元数据 |
| 语义去重 | 新记录入库前检查与现有记忆的语义相似度，避免冗余 |
| 时间衰减 | 旧记忆权重随时间递减，保持知识库时效性 |
| 索引重建 | 支持全量重建 TF-IDF 索引 |
| 历史迁移 | 从 self-learning-skills 一键导入历史 aha cards 和 recs |

## 2) 脚本入口

```bash
python skills/market/smart-memory/scripts/memory.py <command> [options]
```

### 子命令

| 命令 | 说明 |
|------|------|
| `recall --query "需求描述" --tags tag1 tag2 --top 10 --days 30` | 召回相关记忆 |
| `record --title "标题" --when "触发条件" --problem "问题" --solution step1 step2 --evidence src1 src2 --tags tag1 tag2 --gotchas pitfall1 --scope project\|portable` | 记录新知识卡片 |
| `review --days 30 --query "关键词" --status proposed` | 回顾指定时间范围的记忆 |
| `build-index` | 全量重建 TF-IDF 索引（跳过 deprecated） |
| `migrate` | 从 self-learning-skills 一键迁移历史数据 |
| `signal --kind card_recalled --card-id aha_xxx --context "上下文"` | 记录记忆使用信号 |
| `harvest --text "对话摘要" --auto-confirm` | 从对话文本启发式提取候选知识卡片 |
| `session --summary "任务摘要"` | 创建会话快照 |
| `session-list --days 7` | 列出历史会话快照 |

## 3) 存储结构

`D:\hi\.agents\memory\smart-memory\v1\users\hi\`

| 文件/目录 | 说明 |
|------|------|
| `knowledge/cards.jsonl` | 知识卡片 JSONL 数据（含权重、状态、时间戳） |
| `knowledge/index.json` | TF-IDF 索引文件（documents + idf） |
| `signals.jsonl` | 记忆使用信号（recall/reinforced/used）用于衰减追踪 |
| `sessions/` | 会话快照目录 |
| `recommendations.jsonl` | 改进建议记录 |
| `INDEX.md` | 人类可读摘要 |

## 4) 工作流

**⚠️ 以下为强制执行规则，不是可选建议。**

### 触发时机

| 触发事件 | 动作 | 强制性 |
|----------|------|:--:|
| 对话开始时（收到新消息且上一轮无活跃任务） | 执行 `memory.py recall -q "用户消息关键词" --days 30` 召回相关记忆 | 必须 |
| **任何任务完成后**（包括但不限于：创建/修改定时任务、文件操作、配置变更、排查修复、代码生成、文档产出） | **判断本轮是否有可复用经验（排除纯粹查询/只读/一次性结果），有则立即执行 `memory.py record`，不允许跳过或等待用户提醒** | **必须** |
| 可复用经验判定标准 | ①新发现的通用规律/规则 ②配置/参数的具体用法或陷阱 ③验证有效的操作模式或排查链路 ④技能或工具的改进点。满足任一项即为可复用 | — |
| 索引退化检测 | 每 30 天或记忆卡片数增长超过 20% 时执行 `memory.py build-index` | 建议 |

### 执行纪律

- **交付即沉淀**：任务结果交付给用户的同时完成 record，两步不可分割。不得以"等用户确认后再记录"为借口推迟，record 先执行，用户后续否定可删除对应卡片
