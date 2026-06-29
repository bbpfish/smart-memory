# smart-memory

分层长期记忆管理技能 —— 任务前自动 TF-IDF 召回相关记忆，任务后持久化知识卡片。

## 特性

- **记忆召回**：任务前根据用户需求在知识库中 TF-IDF 检索，将 Top-K 相关记忆注入当前上下文
- **记忆记录**：任务后将可复用经验持久化为知识卡片，含时间戳和元数据
- **语义去重**：新记录入库前检查与现有记忆的 TF-IDF 余弦相似度，避免冗余
- **时间衰减**：旧记忆权重随时间递减，保持知识库时效性
- **索引重建**：支持全量重建 TF-IDF 索引
- **历史迁移**：从 self-learning-skills 一键导入历史数据
- **对话收割**：从对话文本启发式提取候选知识卡片

## 依赖

| 依赖项 | 说明 |
|--------|------|
| Python | 3.8 及以上 |
| 外部包 | **零依赖**，仅使用 Python 标准库（json / hashlib / argparse / pathlib / collections / math / re / datetime） |
| 磁盘 | 轻量本地存储（JSONL + JSON），默认路径 `~/.agents/memory/smart-memory/` |
| API / 网络 | 无，完全离线运行 |

## 安装

```bash
git clone https://github.com/bbpfish/smart-memory.git
```

放到你的 Agent 技能目录（取决于你使用的框架）：

| 框架 | 路径 |
|------|------|
| Marvis | `skills/market/smart-memory/` |
| OpenClaw | `~/.agents/skills/smart-memory/` 或 `/skills/smart-memory/` |
| Claude Code | `~/.claude/skills/smart-memory/` |

## 使用

```bash
python scripts/memory.py <command> [options]
```

### 子命令

| 命令 | 说明 |
|------|------|
| `recall --query "需求描述" --tags tag1 --top 10 --days 30` | 召回相关记忆 |
| `record --title "标题" --when "触发条件" --problem "问题" --solution step1 step2 --evidence src1 src2 --tags tag1 tag2` | 记录知识卡片 |
| `review --days 30 --query "关键词" --status proposed` | 回顾面板 |
| `build-index` | 全量重建 TF-IDF 索引 |
| `migrate` | 从 self-learning-skills 迁移历史数据 |
| `signal --kind card_recalled --card-id xxx --context "上下文"` | 记录记忆使用信号 |
| `harvest --text "对话摘要" --auto-confirm` | 对话启发式收割 |
| `session --summary "任务摘要"` | 创建会话快照 |
| `session-list --days 7` | 列出历史会话快照 |
| `dedup --threshold 0.45` | 语义去重检测 |

### 去重机制

三层防护：
1. **record() 阶段一**：精确 ID 去重 —— 相同 ID 按 reinforced_concurrent 处理
2. **record() 阶段二**：标题前 50 字哈希去重 —— 完全相同直接拒绝
3. **dedup 子命令**：TF-IDF 余弦相似度 pairwise 比对 —— 阈值默认 0.45，检出高度相似对

## 存储结构

```
~/.agents/memory/smart-memory/v1/users/<username>/
├── knowledge/
│   ├── cards.jsonl        # 知识卡片数据
│   └── index.json         # TF-IDF 索引
├── signals.jsonl          # 使用信号与衰减追踪
├── sessions/              # 会话快照
├── recommendations.jsonl  # 改进建议
└── INDEX.md               # 人类可读摘要
```

## 自动化维护（铲屎将）

安装技能后建议创建定时任务，每日自动执行记忆优化与技能自进化：

```bash
bash scripts/maintenance.sh
```

**执行流程**：

| 步骤 | 操作 | 说明 |
|------|------|------|
| 1 | 对话收割 | 从最近 1 天对话中启发式提取候选知识卡片 |
| 2 | 语义去重 | 检测高度相似的记忆对，避免冗余 |
| 3 | 索引重建 | 新卡片纳入 TF-IDF 索引，保证召回率 |

**接入定时**（任选一种）：

| 框架 | 方式 |
|------|------|
| Marvis | 安装后告诉 Agent：「帮我创建定时任务，每天凌晨 3 点执行 `python scripts/memory.py harvest --days 1 --auto-confirm && python scripts/memory.py dedup && python scripts/memory.py build-index`」 |
| Linux cron | `0 3 * * * bash /path/to/smart-memory/scripts/maintenance.sh` |
| Windows 计划任务 | 触发器每日一次，操作为 `bash maintenance.sh` |
| GitHub Actions | `schedule: cron: '0 3 * * *'` |

## 兼容性

本技能遵循 [AgentSkills 开放标准](https://github.com/anthropics/agent-skills)（Anthropic 2025），开箱兼容：

- Marvis
- OpenClaw
- Claude Code
- Codex CLI
- Cursor

## 许可证

MIT License
