#!/bin/sh
# 铲屎将 — 智能记忆优化与技能自进化
# 用法: bash maintenance.sh [--dry-run]
# 推荐频率: 每天一次（cron: 0 3 * * *）

set -e
DRY_RUN=false
[ "$1" = "--dry-run" ] && DRY_RUN=true

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MEMORY_PY="$SCRIPT_DIR/memory.py"

echo "=== 铲屎将 开始 $(date '+%Y-%m-%d %H:%M:%S') ==="

# 1. 对话收割：从最近对话提取知识卡片
echo "[1/3] 对话收割..."
if [ "$DRY_RUN" = true ]; then
    python "$MEMORY_PY" harvest --days 1 --auto-confirm --dry-run
else
    python "$MEMORY_PY" harvest --days 1 --auto-confirm
fi

# 2. 语义去重：检测高度相似的记忆对
echo "[2/3] 语义去重检测..."
python "$MEMORY_PY" dedup --threshold 0.45

# 3. 重建索引：新卡片纳入 TF-IDF
echo "[3/3] 重建索引..."
python "$MEMORY_PY" build-index

echo "=== 铲屎将 完成 $(date '+%Y-%m-%d %H:%M:%S') ==="
