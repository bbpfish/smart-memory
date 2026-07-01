#!/bin/sh
# 记忆系统维护 — 智能记忆优化与技能自进化 (P3 炼知识版)
# 用法: bash maintenance.sh [--dry-run]
# 推荐频率: 每天一次（cron: 0 3 * * *）

set -e
DRY_RUN=false
[ "$1" = "--dry-run" ] && DRY_RUN=true

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MEMORY_PY="$SCRIPT_DIR/memory.py"

echo "=== 铲屎将 开始 $(date '+%Y-%m-%d %H:%M:%S') ==="

# 1. 对话收割：从最近对话提取知识卡片
echo "[1/6] 对话收割..."
if [ "$DRY_RUN" = true ]; then
    python "$MEMORY_PY" harvest --days 1 --auto-confirm --dry-run
else
    python "$MEMORY_PY" harvest --days 1 --auto-confirm
fi

# 2. 语义去重：检测高度相似的记忆对
echo "[2/6] 语义去重检测..."
python "$MEMORY_PY" dedup --threshold 0.45

# 3. 知识合成：聚类相似卡片生成综述卡（P3）
echo "[3/6] 知识合成..."
if [ "$DRY_RUN" = true ]; then
    python "$MEMORY_PY" synthesize --threshold 0.6 --min-cluster-size 2
else
    python "$MEMORY_PY" synthesize --threshold 0.6 --min-cluster-size 2 --auto-write
fi

# 4. 跨卡关联：向量相似度发现卡片间隐藏联系（P3）
echo "[4/6] 跨卡关联..."
if [ "$DRY_RUN" = true ]; then
    python "$MEMORY_PY" cross-link --threshold 0.5 --top-k 3
else
    python "$MEMORY_PY" cross-link --threshold 0.5 --top-k 3 --auto-write
fi

# 5. 信号分析：更新知识成熟度评分（P3）
echo "[5/6] 信号分析..."
if [ "$DRY_RUN" = true ]; then
    python "$MEMORY_PY" signal-analysis --days 30
else
    python "$MEMORY_PY" signal-analysis --days 30 --auto-write
fi

# 6. 重建索引：新卡片纳入 TF-IDF + 向量索引
echo "[6/6] 重建索引..."
python "$MEMORY_PY" build-index

echo "=== 铲屎将 完成 $(date '+%Y-%m-%d %H:%M:%S') ==="
