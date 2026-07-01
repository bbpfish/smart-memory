---
name: smart-memory
version: 2.3.1
description: 分层长期记忆管理系统：任务前自动 TF-IDF 召回相关记忆，任务后持久化知识卡片，支持语义去重、时间衰减权重、全量索引重建、LLM 结构化收割，可从 self-learning-skills 一键迁移历史数据。
---

# 分层长期记忆管理

任务前自动从知识库召回相关历史经验，任务后持久化新知识卡片。

## 1) 核心命令

脚本入口：`python skills/market/smart-memory/scripts/memory.py <command>`

| 命令 | 用途 |
|------|------|
| `recall -q "关键词" --top 8 --days 30` | 召回相关记忆，注入当前上下文 |
| `record --title ... --when ... --problem ... --solution ... --tags ...` | 记录知识卡片，自动去重 |
| `harvest --text "摘要" --auto-confirm` | 从对话摘要自动提取并写入知识卡片（启发式正则） |
| `harvest-structured --text "结构化文本" --auto-confirm` | 从 LLM 预提取的结构化文本直接入库（方法1），格式见下方 |
| `harvest-structured --file "path/to/cards.md" --auto-confirm` | 同上，从文件读取结构化文本 |
| `review --days 30 --query "关键词"` | 回顾指定时间范围的记忆 |

### `harvest-structured` 输入格式

agent（LLM）对原始对话做结构化提取后，输出以下 Markdown 格式，`harvest-structured` 直接解析入库：

```
## 卡片1
标题: <一句话标题>
何时使用: <触发条件>
问题: <遇到的具体问题>
解决方案: <解决步骤>
标签: <tag1>, <tag2>

## 卡片2
标题: <标题>
何时使用: <条件>
问题: <问题>
解决方案: <方案>
标签: <tag1>
```

- 以 `## 卡片N` / `## 经验N` / `## 知识N` / `## 记忆N` 分隔每张卡片
- 其他 `## xxx` 块（如 `## 总结`）自动跳过
- 解决方案支持多行续写（无字段前缀的行追加到上一字段）
- 标签按逗号、顿号、空格拆分（最多 8 个）
- `--auto-confirm` 直接写入 cards.jsonl，否则预览候选
| `build-index` | 全量重建 TF-IDF + 向量索引 |
| `build-index --auto` | 仅当索引退化时重建（年龄 > 30 天 或 卡片 +20%） |
| `check-index` | 检查索引健康状态，输出退化原因 |
| `compact` | 紧凑化 cards.jsonl，去除因 reinforcement 产生的重复 ID 行 |
| `migrate` | 从 self-learning-skills 迁移历史数据 |
| `dedup --threshold 0.45` | 语义相似度去重检测 |
| `recalc-decay --dry-run` | 批量更新所有卡片的 retention（遗忘曲线）和 importance |
| `recalc-decay --save-baseline` | 同上，且更新前保存 retention 基线快照供巡检对比 |
| `decay-report` | 对比 baseline 与当前 retention，检测衰减卡片 |

## 2) 存储结构

根目录：`D:\hi\.agents\memory\smart-memory\v1\users\hi\`

| 文件 | 说明 |
|------|------|
| `knowledge/cards.jsonl` | 知识卡片数据（权重、状态、时间戳、retention、importance） |
| `knowledge/index.json` | TF-IDF 索引 |
| `signals.jsonl` | 使用信号（recall/reinforced/used） |
| `recommendations.jsonl` | 改进建议记录 |
| `knowledge/retention_baseline.json` | recalc-decay 前的 retention 快照，巡检衰减对比基准 |

## 3) Ebbinghaus 遗忘曲线

每张知识卡片新增 `retention`（0~1）和 `importance`（0~1）字段：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `retention` | 1.0 | 基于 Ebbinghaus 模型 `R(t)=R₀×e^(-t/S)`，`S=importance×720`（小时） |
| `importance` | 0.5 | 可通过 `record --importance 0.8` 设置，值越高遗忘越慢 |

每次 recall/reinforce/used 信号触发时：
1. 先按遗忘曲线衰减当前 retention
2. 再加 reinforcement boost（recall +0.3, used +0.5, reinforce +0.5）
3. 上限 1.0

`retention < 0.1` 的卡片可视为待废弃候选。

**巡检衰减检测**：`decay-report` 对比上一次 `recalc-decay --save-baseline` 保存的基线快照，检测两次重算间的真实遗忘。下降 >20% 的卡片被标记为衰减告警。首日 baseline 不存在时自动跳过衰减对比。

## 4) 工作流（强制执行）

| 触发 | 动作 |
|------|------|
| 对话开始 | `recall -q "用户消息关键词" --top 8 --days 30` |
| 任务完成且有可复用经验 | 立即 `record`，交付即沉淀，不等用户确认 |
| 索引退化检测 | `build-index --auto`（自动跳过健康索引） |

可复用经验判定：通用规律、配置用法/陷阱、有效操作模式、技能改进点。纯粹查询/只读不算。

## 5) 性能概况

| 指标 | 当前值 | 警戒线 | 对策 |
|------|--------|--------|------|
| recall 耗时 | ~170ms | >500ms | `build-index` |
| 索引体积 | ~1.2MB (TF-IDF+向量) | >5MB | 归档废弃卡片后 rebuild |
| 上下文注入 | ~8KB (12条) | >20KB | 降低 `--top` 到 5-6 |
| 卡片总数 | ~295 条 | >500 | `dedup` 合并相似 |
