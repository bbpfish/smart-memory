# ClawdHub 发布流程

> **私有文档**：本文件仅供定时任务智能记忆巡检 Step 12.4 引用，严禁同步到 nightly-maintenance.yaml.example 公开模板或 ClawdHub 市场。

## 前置条件

同时满足以下两项才执行发布：

1. Step 12.3 对 YAML prompt 做了修正（修正数 M > 0）
2. `E:\marvis-skills\smart-memory` 仓库有**实质代码变更**，而非仅 YAML prompt 对齐

判定方法：

```powershell
git -C E:\marvis-skills\smart-memory diff --name-only HEAD~1
```

若 diff 结果**仅含** `schedules/*.yaml` → 跳过发布。若含 `SKILL.md` 或 `scripts/*.py` → 有实质变更。

## 版本号规则

- `clawhub info bbpfish/smart-memory` 查询市场当前版本
- 读取 `E:\marvis-skills\smart-memory\SKILL.md` 中 `version:` 字段
- 本地版本 > 市场版本 或 版本相同但代码有变更 → 执行发布
- 发布前：SKILL.md version patch +1（如 2.3.3 → 2.3.4）

## 执行步骤

```powershell
# 1. 判定实质变更
git -C E:\marvis-skills\smart-memory diff --name-only HEAD~1

# 2. 检查市场版本
clawhub info bbpfish/smart-memory

# 3. 递增版本号（edit SKILL.md version 字段）

# 4. 发布
clawhub publish E:\marvis-skills\smart-memory `
  --slug smart-memory `
  --name "Smart Memory" `
  --version <x.y.z> `
  --tags "memory,agent,self-evolving" `
  --changelog "<本次修正摘要>"

# 5. Git 提交推送
git -C E:\marvis-skills\smart-memory add -A
git -C E:\marvis-skills\smart-memory commit -m "chore: auto-publish v<x.y.z>"
git -C E:\marvis-skills\smart-memory push
```

## 边界情况

| 情况 | 行为 |
|---|---|
| 仅 YAML prompt 对齐 | 跳过发布，输出「跳过-仅 prompt 对齐」 |
| 无修正（M=0） | 跳过，输出「跳过-无修正」 |
| 有修正但无实质代码变更 | 跳过，输出「跳过-仅 prompt 对齐」 |
| 有修正且有实质代码变更 | 执行完整发布流程 |
| 本地版本 ≤ 市场版本且代码无变更 | 跳过，输出「跳过-版本已同步」 |

## 与公开模板的隔离

- `nightly-maintenance.yaml.example`：公开模板，**不含任何 ClawdHub 发布指令**，不引用本文件
- 产出报告中「ClawdHub 同步」行：仅在实际 YAML 的 Step 13 报告中出现，`nightly-maintenance.yaml.example` 中删除此行
- 12.3 自动修正 prompt 时，**不得**将本文件的引用同步到 `nightly-maintenance.yaml.example`
