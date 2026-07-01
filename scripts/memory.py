#!/usr/bin/env python3
r"""
smart-memory CLI — 分层记忆管理系统

Store: D:\hi\.agents\memory\smart-memory\v1\users\hi\

架构:
  sessions/       — 会话级记忆（自动收割的快照）
  knowledge/      — 项目级知识卡片 + TF-IDF 索引
  recommendations.jsonl — 改进建议
  signals.jsonl   — 使用信号与衰减追踪
  INDEX.md        — 人类可读摘要

依赖: Python stdlib only
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import os
import re
import sys
import time

# ── Windows 控制台编码修复 ─────────────────────────────
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── 路径常量 ──────────────────────────────────────────
SKILL_DIR = Path(__file__).resolve().parent.parent
STORE_ROOT = Path("D:/hi/.agents/memory/smart-memory/v1/users/hi")
SESSION_DIR = STORE_ROOT / "sessions"
KNOWLEDGE_DIR = STORE_ROOT / "knowledge"
CARDS_FILE = KNOWLEDGE_DIR / "cards.jsonl"
INDEX_FILE = KNOWLEDGE_DIR / "index.json"
VECTOR_INDEX_FILE = KNOWLEDGE_DIR / "index_vectors.npz"
INDEX_META_FILE = KNOWLEDGE_DIR / "index_meta.json"
RECS_FILE = STORE_ROOT / "recommendations.jsonl"
SIGNALS_FILE = STORE_ROOT / "signals.jsonl"
BASELINE_FILE = KNOWLEDGE_DIR / "retention_baseline.json"
INDEX_MD = STORE_ROOT / "INDEX.md"

# ── 工具函数 ──────────────────────────────────────────
def iso_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _ts_to_dt(ts: str) -> _dt.datetime:
    s = ts.strip().replace(" ", "T").replace("Z", "+00:00")
    return _dt.datetime.fromisoformat(s)

def _hash_id(text: str, prefix: str = "sm") -> str:
    h = hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{h}"

def _load_jsonl(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    items = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return items

def _append_jsonl(path: Path, obj: Dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def _write_json(path: Path, obj: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)

def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return json.load(f)

# ── TF-IDF 简易索引 ───────────────────────────────────
class TfidfIndex:
    """轻量 TF-IDF 索引，无外部依赖"""

    def __init__(self, index_path: Path = INDEX_FILE):
        self.index_path = index_path
        self.documents: Dict[str, Dict] = {}   # id → {tokens, weights}
        self.idf: Dict[str, float] = {}
        self._dirty = False

    def load(self):
        data = _read_json(self.index_path)
        if data:
            self.documents = data.get("documents", {})
            self.idf = data.get("idf", {})
        return self

    def save(self):
        _write_json(self.index_path, {
            "documents": self.documents,
            "idf": self.idf,
            "updated": iso_now()
        })

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """中文按字+2-gram，英文按词，去停用词"""
        # 简易 tokenizer
        tokens = []
        # 预处理：移除替换字符（U+FFFD），防止编码损坏传播到索引
        text = text.replace('\ufffd', '')
        # 提取中文字符
        cn_chars = re.findall(r'[\u4e00-\u9fff]+', text.lower())
        for seg in cn_chars:
            if len(seg) >= 2:
                for i in range(len(seg) - 1):
                    tokens.append(seg[i:i + 2])
            tokens.append(seg)
        # 提取英文词
        en_words = re.findall(r'[a-z0-9]{2,}', text.lower())
        tokens.extend(en_words)
        # 过滤纯数字和单字符
        stop_words = {'the', 'and', 'for', 'with', 'this', 'that', 'from', 'have', 'has'}
        return [t for t in tokens if t not in stop_words and not t.isdigit()]

    def add(self, doc_id: str, text: str, weight: float = 1.0):
        tokens = self._tokenize(text)
        tf = Counter(tokens)
        self.documents[doc_id] = {"tokens": tokens, "weights": dict(tf), "base_weight": weight}
        # 更新 IDF
        n = len(self.documents)
        for token in set(tokens):
            df = sum(1 for d in self.documents.values() if token in d["weights"])
            self.idf[token] = math.log((n + 1) / (df + 1)) + 1.0
        self._dirty = True

    def remove(self, doc_id: str):
        if doc_id in self.documents:
            del self.documents[doc_id]
            self._dirty = True

    def search(self, query: str, top_k: int = 10) -> List[Tuple[str, float]]:
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []
        scores: Dict[str, float] = {}
        q_tf = Counter(query_tokens)
        q_len = math.sqrt(sum(v ** 2 for v in q_tf.values()))
        for doc_id, doc in self.documents.items():
            d_weights = doc["weights"]
            dot = 0.0
            d_len_sq = 0.0
            for token, d_w in d_weights.items():
                d_len_sq += d_w ** 2
                if token in q_tf:
                    idf = self.idf.get(token, 1.0)
                    dot += q_tf[token] * d_w * (idf ** 2)
            d_len = math.sqrt(d_len_sq)
            if q_len > 0 and d_len > 0:
                cosine = dot / (q_len * d_len)
                base_w = doc.get("base_weight", 1.0)
                scores[doc_id] = cosine * base_w
        return sorted(scores.items(), key=lambda x: -x[1])[:top_k]


# ══════════════════════════════════════════════════════
# P2: 向量语义检索索引（ONNX + MiniLM 多语言模型）
# ══════════════════════════════════════════════════════
import numpy as np  # noqa: E402

_MODEL_DIR = SKILL_DIR / "models" / "paraphrase-multilingual-MiniLM-L12-v2"
_VECTOR_DIM = 384  # MiniLM-L12 输出维度
_MAX_SEQ_LEN = 128


class VectorIndex:
    """语义向量索引，基于 ONNX 多语言 MiniLM 模型

    PURE STRATEGY: 在现有 TF-IDF 之上叠加语义检索，不替代
    """

    _session = None
    _tokenizer = None

    def __init__(self, index_path: Path = VECTOR_INDEX_FILE):
        self.index_path = index_path
        self.ids: List[str] = []
        self.vectors: Optional[np.ndarray] = None  # shape (n, 384)

    # ── 模型懒加载（进程级单例）─────────────────────
    @classmethod
    def _get_session(cls):
        if cls._session is None:
            import onnxruntime  # noqa: E402
            cls._session = onnxruntime.InferenceSession(
                str(_MODEL_DIR / "onnx" / "model_quint8_avx2.onnx"),
                providers=["CPUExecutionProvider"],
            )
        return cls._session

    @classmethod
    def _get_tokenizer(cls):
        if cls._tokenizer is None:
            from tokenizers import Tokenizer  # noqa: E402
            cls._tokenizer = Tokenizer.from_file(str(_MODEL_DIR / "tokenizer.json"))
        return cls._tokenizer

    @classmethod
    def _embed(cls, texts: List[str]) -> np.ndarray:
        """批量文本 → L2 归一化向量"""
        if not texts:
            return np.empty((0, _VECTOR_DIM), dtype=np.float32)
        tokenizer = cls._get_tokenizer()
        session = cls._get_session()
        # Tokenize
        input_ids_list = []
        masks = []
        for t in texts:
            enc = tokenizer.encode(t)
            ids = enc.ids[:_MAX_SEQ_LEN]
            m = enc.attention_mask[:_MAX_SEQ_LEN]
            pad = _MAX_SEQ_LEN - len(ids)
            if pad > 0:
                ids += [0] * pad
                m += [0] * pad
            input_ids_list.append(ids)
            masks.append(m)
        input_ids = np.array(input_ids_list, dtype=np.int64)
        attention_mask = np.array(masks, dtype=np.int64)
        token_type_ids = np.zeros_like(input_ids, dtype=np.int64)
        # Inference
        outputs = session.run(None, {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "token_type_ids": token_type_ids,
        })
        embeddings = outputs[0].astype(np.float32)
        # Mean pooling + L2 normalize
        mask_exp = attention_mask[:, :, np.newaxis].astype(np.float32)
        summed = np.sum(embeddings * mask_exp, axis=1)
        count = np.clip(np.sum(mask_exp, axis=1), 1e-9, None)
        mean = summed / count
        norms = np.linalg.norm(mean, axis=1, keepdims=True)
        return mean / np.clip(norms, 1e-9, None)

    @staticmethod
    def _build_text(card: Dict) -> str:
        """构造索引文本（与 TfidfIndex 对齐）"""
        return f"{card.get('title','')} {card.get('when_to_use','')} {card.get('problem','')} {' '.join(card.get('tags',[]))}"

    # ── 索引操作 ────────────────────────────────────
    def load(self):
        if self.index_path.exists():
            data = np.load(self.index_path, allow_pickle=True)
            self.ids = data["ids"].tolist()
            self.vectors = data["vectors"]
        else:
            self.ids = []
            self.vectors = None
        return self

    def save(self):
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            self.index_path,
            ids=np.array(self.ids, dtype=object),
            vectors=self.vectors if self.vectors is not None else np.empty((0, _VECTOR_DIM), dtype=np.float32),
        )

    def add(self, doc_id: str, text: str):
        """添加单条文档向量"""
        vec = self._embed([text])[0]
        if doc_id in self.ids:
            idx = self.ids.index(doc_id)
            self.vectors[idx] = vec
        else:
            self.ids.append(doc_id)
            if self.vectors is None:
                self.vectors = np.array([vec], dtype=np.float32)
            else:
                self.vectors = np.vstack([self.vectors, vec])

    def remove(self, doc_id: str):
        if doc_id in self.ids:
            idx = self.ids.index(doc_id)
            self.ids.pop(idx)
            if len(self.ids) == 0:
                self.vectors = None
            else:
                self.vectors = np.delete(self.vectors, idx, axis=0)

    def search(self, query: str, top_k: int = 10) -> List[Tuple[str, float]]:
        """向量相似度搜索，返回 [(card_id, cosine_similarity), ...]"""
        if self.vectors is None or len(self.ids) == 0:
            return []
        q_vec = self._embed([query])[0]
        sims = np.dot(self.vectors, q_vec)  # (n,) cosine sim (向量已 L2 归一化)
        top_indices = np.argsort(-sims)[:top_k]
        return [(self.ids[i], float(sims[i])) for i in top_indices if sims[i] > 0]

    def rebuild_from_cards(self, cards: List[Dict]):
        """从 cards.jsonl 全量重建向量索引"""
        latest: Dict[str, Dict] = {}
        for c in cards:
            cid = c.get("id", "")
            if cid and c.get("status") != "deprecated":
                latest[cid] = c
        self.ids = list(latest.keys())
        texts = [self._build_text(c) for c in latest.values()]
        if texts:
            self.vectors = self._embed(texts)
        else:
            self.vectors = None
        self.save()
        return len(self.ids)

    @property
    def count(self) -> int:
        return len(self.ids)


# ── 核心操作 ──────────────────────────────────────────

def _get_retention_params(card: Dict) -> Tuple[float, float]:
    """计算卡片的 retention 参数：(半衰期_天, 分数乘数)

    固化卡片获得更慢衰减和更高基础权重。

    分级规则:
      - 合成卡片 (_synthesis_of 存在)  → 半衰期 60 天, 2.0x
      - 成熟度 >= 0.85                   → 半衰期 60 天, 2.0x
      - 成熟度 >= 0.70                   → 半衰期 45 天, 1.5x
      - 默认                            → 半衰期 30 天, 1.0x
    """
    # 合成卡片优先
    if card.get("_synthesis_of"):
        return 60.0, 2.0
    ms = card.get("maturity_score", 0)
    if ms >= 0.85:
        return 60.0, 2.0
    if ms >= 0.70:
        return 45.0, 1.5
    return 30.0, 1.0


def recall(query: str = "", tags: List[str] = None, top_k: int = 10,
           days: int = 30, mode: str = "hybrid") -> List[Dict]:
    """
    任务前召回：TF-IDF 匹配 + 向量语义检索 + 标签过滤 + 差异化时间衰减

    固化卡片（合成卡 / 高成熟度）获得更长半衰期和更高权重基数。
    mode: "tfidf" | "vector" | "hybrid"（默认 hybrid）
    """
    cards_all = _load_jsonl(CARDS_FILE)
    # 建立 id→card 映射（取最新版本）
    card_map: Dict[str, Dict] = {}
    for c in cards_all:
        cid = c.get("id", "")
        if cid:
            card_map[cid] = c

    if not query:
        # 无 query 时返回最近高权重的
        hits = [(cid, c.get("weight", 1.0)) for cid, c in card_map.items()]
        hits.sort(key=lambda x: -x[1])
    else:
        if mode == "tfidf":
            idx = TfidfIndex().load()
            hits = idx.search(query, top_k=top_k * 2)
        elif mode == "vector":
            vidx = VectorIndex().load()
            hits = vidx.search(query, top_k=top_k * 2)
        else:  # hybrid (default)
            idx = TfidfIndex().load()
            tfidf_hits = idx.search(query, top_k=top_k * 2)
            vidx = VectorIndex().load()
            vector_hits = vidx.search(query, top_k=top_k * 2)
            # ── 分数融合：Reciprocal Rank Fusion + 原始分数加权 ──
            # TF-IDF 分数归一化
            tfidf_max = max((s for _, s in tfidf_hits), default=1.0)
            tfidf_scores = {cid: s / max(tfidf_max, 0.01) for cid, s in tfidf_hits}
            # Vector 分数（已在 0~1 的余弦相似度）
            vector_scores = {cid: s for cid, s in vector_hits}
            # 融合：TF-IDF 权重 0.4，向量权重 0.6
            all_ids = set(tfidf_scores.keys()) | set(vector_scores.keys())
            fused = {}
            for cid in all_ids:
                tf_score = tfidf_scores.get(cid, 0.0)
                vec_score = vector_scores.get(cid, 0.0)
                fused[cid] = tf_score * 0.4 + vec_score * 0.6
            hits = sorted(fused.items(), key=lambda x: -x[1])[:top_k * 2]

    # 标签过滤
    if tags:
        tag_set = set(tags)
        hits = [(cid, s) for cid, s in hits
                if cid in card_map and tag_set & set(card_map[cid].get("tags", []))]

    # 时间衰减 + 去重
    now = _dt.datetime.now(_dt.timezone.utc)
    results = []
    seen_titles = set()
    for card_id, score in hits:
        card = card_map.get(card_id)
        if not card:
            continue
        ts = card.get("ts", iso_now())
        try:
            age_days = (now - _ts_to_dt(ts)).days
        except Exception:
            age_days = 0
        # 差异化衰减：固化卡片获得更长半衰期和权重加成
        half_life, boost = _get_retention_params(card)
        decay = 0.5 ** (age_days / half_life)
        final_score = score * boost * decay

        # 去重：相似 title
        title_key = card.get("title", "").strip().lower()[:20]
        if title_key in seen_titles and final_score < 1.0:
            continue
        seen_titles.add(title_key)

        if final_score > 0.01 or not query:
            results.append({**card, "_score": round(final_score, 4)})

    results.sort(key=lambda x: -x["_score"])
    # 自动为召回结果写信号
    for r in results[:top_k]:
        signal("card_recalled", r["id"], context=f"query={query[:60]}")
    return results[:top_k]


def _repair_encoding(text: str) -> str:
    """修复 Latin-1 误读 UTF-8 字节产生的编码损坏（mojibake）。
    
    症状: "æ¸\x85ç\x90\x86" → 应恢复为 "清理"
    原理: UTF-8 编码的中文字节被当作 Latin-1/CP1252 解码后，
         再次以 UTF-8 写入，形成双重编码损坏。逆转此过程。
    """
    if not text or not isinstance(text, str):
        return text
    try:
        restored = text.encode("latin-1").decode("utf-8")
        # 仅当恢复后包含真实中文字符时才认为修复成功
        if restored != text and any('\u4e00' <= c <= '\u9fff' for c in restored):
            return restored
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return text


def _normalize_tags(tags: List[str]) -> List[str]:
    """归一化标签列表：
    把 ['tag1, tag2, tag3'] (单个逗号分隔字符串) 拆分为 ['tag1', 'tag2', 'tag3']，
    并去除空白和空串。此修复解决 argparse nargs='*' 与 shell 引号组合导致的单元素逗号串问题。
    """
    normalized = []
    for t in (tags or []):
        for part in t.split(','):
            part = part.strip()
            if part:
                normalized.append(part)
    return normalized


def _auto_compact_maybe():
    """当 cards.jsonl 总行数超过唯一 ID 数的 1.3 倍时，自动触发 compact"""
    cards = _load_jsonl(CARDS_FILE)
    total = len(cards)
    unique = len(set(c.get("id", "") for c in cards if c.get("id")))
    if unique > 0 and total > unique * 1.3:
        try:
            compact()
        except Exception:
            pass  # compact 失败不影响主流程


def _normalize_sig(text: str) -> str:
    """标准化签名文本：去首尾空白、压缩连续空格、统一换行"""
    return re.sub(r'\s+', ' ', text.strip().lower())


def record(title: str, when_to_use: str, problem: str,
           solution_steps: List[str], evidence: List[str] = None,
           tags: List[str] = None, gotchas: List[str] = None,
           scope: str = "project", **kwargs):
    """
    记录一条知识卡片，自动去重与索引，自动写信号。
    """
    # 修复可能从 subprocess GBK 边界传入的编码损坏
    title = _repair_encoding(title)
    when_to_use = _repair_encoding(when_to_use)
    problem = _repair_encoding(problem)
    solution_steps = [_repair_encoding(s) for s in (solution_steps or [])]
    evidence = [_repair_encoding(s) for s in (evidence or [])]
    tags = _normalize_tags([_repair_encoding(s) for s in (tags or [])])
    gotchas = [_repair_encoding(s) for s in (gotchas or [])]

    # 标准化签名文本（去空格差异、大小写差异）
    sig_title = _normalize_sig(title)
    sig_when = _normalize_sig(when_to_use)
    sig_problem = _normalize_sig(problem)
    sig_text = f"{sig_title}|{sig_when}|{sig_problem}"
    card_id = _hash_id(sig_text, "smc")

    # 检查是否已存在相似卡片（ID 精确匹配 OR title 相近匹配）
    existing = _load_jsonl(CARDS_FILE)
    seen_ids = set()
    for old in reversed(existing):  # 从最新开始查
        old_id = old.get("id", "")
        if old_id in seen_ids:
            continue
        seen_ids.add(old_id)

        # 精确 ID 匹配
        if old_id == card_id:
            old_weight = old.get("weight", 1.0)
            new_card = {**old, "weight": round(old_weight + 0.5, 2),
                       "reinforced_ts": iso_now(), "reinforced_count": old.get("reinforced_count", 0) + 1}
            _append_jsonl(CARDS_FILE, new_card)
            idx = TfidfIndex().load()
            if card_id in idx.documents:
                idx.documents[card_id]["base_weight"] = new_card["weight"]
                idx.save()
            signal("card_reinforced", card_id, context=title)
            _auto_compact_maybe()
            return {"id": card_id, "action": "reinforced", "weight": new_card["weight"]}

        # 标题相似匹配（前 50 字符完全相同 → 视为同一经验）
        old_title = _normalize_sig(old.get("title", ""))
        if old_title[:50] == sig_title[:50] and len(old_title) > 10:
            # 合并 solution_steps
            merged_solutions = list(dict.fromkeys(
                (old.get("solution_steps") or []) + (solution_steps or [])
            ))
            merged_evidence = list(dict.fromkeys(
                (old.get("evidence") or []) + (evidence or [])
            ))
            new_card = {
                **old,
                "weight": round(old.get("weight", 1.0) + 0.3, 2),
                "reinforced_ts": iso_now(),
                "reinforced_count": old.get("reinforced_count", 0) + 1,
                "solution_steps": merged_solutions,
                "evidence": merged_evidence,
                "problem": problem if len(problem) > len(old.get("problem", "")) else old.get("problem", ""),
            }
            _append_jsonl(CARDS_FILE, new_card)
            signal("card_merged", old_id, context=f"title match: {title[:60]}")
            # 更新向量索引（文本可能扩展）
            vidx = VectorIndex().load()
            index_text = f"{new_card.get('title','')} {new_card.get('when_to_use','')} {new_card.get('problem','')} {' '.join(new_card.get('tags',[]))}"
            vidx.add(old_id, index_text)
            vidx.save()
            _auto_compact_maybe()
            return {"id": old_id, "action": "merged", "weight": new_card["weight"]}

    # 新卡片 — 写入前做二次去重检查（防护并发写入导致重复行）
    card = {
        "id": card_id,
        "ts": iso_now(),
        "title": title,
        "when_to_use": when_to_use,
        "problem": problem,
        "solution_steps": solution_steps,
        "evidence": evidence or [],
        "tags": tags or [],
        "gotchas": gotchas or [],
        "scope": scope,
        "weight": 1.0,
        "reinforced_count": 0,
        "status": "active",
        "retention": 1.0,
    }
    # Merge kwargs keys not already in card
    for k, v in kwargs.items():
        if k not in card:
            card[k] = v
    # Ensure importance default if not provided via kwargs
    card.setdefault("importance", 0.5)
    # 二次确认：重新读取文件最新状态，避免并发/批量写入导致的 ID 重复
    final_check = _load_jsonl(CARDS_FILE)
    for old in reversed(final_check):
        if old.get("id") == card_id:
            # 并发场景下已有同样卡片，按 reinforcement 处理
            old_weight = old.get("weight", 1.0)
            merged_card = {**old, "weight": round(old_weight + 0.5, 2),
                          "reinforced_ts": iso_now(),
                          "reinforced_count": old.get("reinforced_count", 0) + 1}
            _append_jsonl(CARDS_FILE, merged_card)
            signal("card_reinforced", card_id, context=f"concurrent dedup: {title[:60]}")
            _auto_compact_maybe()
            return {"id": card_id, "action": "reinforced_concurrent", "weight": merged_card["weight"]}
    _append_jsonl(CARDS_FILE, card)

    # 建索引
    index_text = f"{title} {when_to_use} {problem} {' '.join(tags or [])}"
    idx = TfidfIndex().load()
    idx.add(card_id, index_text, weight=1.0)
    idx.save()
    # 向量索引
    vidx = VectorIndex().load()
    vidx.add(card_id, index_text)
    vidx.save()

    # 自动写信号
    signal("card_recorded", card_id, context=title[:80])

    _auto_compact_maybe()
    return {"id": card_id, "action": "created", "weight": 1.0}


def _ebbinghaus_decay(card: Dict, now: _dt.datetime) -> float:
    """Ebbinghaus 遗忘曲线衰减：R(t) = R₀ × e^(-t/S)"""
    last = card.get("last_used_ts") or card.get("ts", iso_now())
    try:
        hours = (now - _ts_to_dt(last)).total_seconds() / 3600.0
    except Exception:
        hours = 0.0
    importance = card.get("importance", 0.5)
    S = importance * 720.0  # max half-life ~30 days at importance=1.0
    current_retention = card.get("retention", 1.0)
    decayed = current_retention * math.exp(-hours / max(S, 1.0))
    return round(max(0.01, decayed), 4)


def _calc_importance(card: Dict) -> float:
    """自动计算重要性（0~1）：基于 reinforced_count + weight + retention"""
    rc = card.get("reinforced_count", 0)
    w = card.get("weight", 1.0)
    r = card.get("retention", 1.0)
    # reinforced_count 贡献 0.5，weight 贡献 0.3，retention 贡献 0.2
    score = min(1.0, rc * 0.12 + max(0, w - 1.0) * 0.08 + r * 0.2 + 0.2)
    return round(score, 2)


def batch_decay(dry_run: bool = False, save_baseline: bool = False) -> Dict:
    """批量更新所有卡片的 retention 和 importance

    对每张卡片：先用 Ebbinghaus 遗忘曲线计算当前 retention，
    再基于新 retention 重算 importance。
    仅回写有变化的卡片。

    save_baseline=True 时，先保存衰减前的 retention 快照到 baseline 文件，
    供巡检任务对比两次 recalc-decay 之间的真实衰减。
    """
    cards = _load_jsonl(CARDS_FILE)
    seen = {}
    for c in reversed(cards):
        cid = c.get("id", "")
        if cid and cid not in seen:
            seen[cid] = c

    if save_baseline:
        _save_baseline(seen)

    now = _dt.datetime.now(_dt.timezone.utc)
    total = len(seen)
    retention_changed = 0
    importance_changed = 0

    for cid, c in seen.items():
        new_ret = _ebbinghaus_decay(c, now)
        old_ret = c.get("retention", 1.0)
        if abs(new_ret - old_ret) > 0.001:
            retention_changed += 1
            c["retention"] = new_ret

        new_imp = _calc_importance(c)
        old_imp = c.get("importance", 0.5)
        if abs(new_imp - old_imp) > 0.01:
            importance_changed += 1
            c["importance"] = new_imp

        if not dry_run and (abs(new_ret - old_ret) > 0.001 or abs(new_imp - old_imp) > 0.01):
            _append_jsonl(CARDS_FILE, c)

    return {
        "total_cards": total,
        "retention_updated": retention_changed,
        "importance_updated": importance_changed,
        "dry_run": dry_run,
    }


def _save_baseline(cards: Dict[str, Dict]) -> None:
    """保存 retention baseline 快照，用于巡检对比衰减"""
    snapshot = {}
    for cid, c in cards.items():
        snapshot[cid] = {
            "retention": c.get("retention", 1.0),
            "importance": c.get("importance", 0.5),
        }
    data = {"saved_at": iso_now(), "cards": snapshot}
    BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(BASELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_baseline() -> Optional[Dict]:
    """加载 retention baseline"""
    if not BASELINE_FILE.exists():
        return None
    with open(BASELINE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def decay_report() -> Dict:
    """对比 baseline 与当前 retention，输出衰减报告

    返回：
    - baseline_age_hours: baseline 距今小时数
    - total_in_baseline: baseline 中的卡片数
    - total_current: 当前卡片数（去重）
    - total_decayed: retention 下降 > 20% 的卡片数
    - total_new: 不在 baseline 中的新卡片
    - decayed_cards: [{id, baseline_ret, current_ret, drop_pct, importance}]
    """
    baseline = _load_baseline()
    if baseline is None:
        return {"error": "no_baseline", "message": "尚未保存 baseline，请先执行 recalc-decay --save-baseline"}

    baseline_cards = baseline.get("cards", {})
    saved_at = baseline.get("saved_at", "")
    try:
        age = (_dt.datetime.now(_dt.timezone.utc) - _ts_to_dt(saved_at)).total_seconds() / 3600.0
    except Exception:
        age = 0.0

    # 读取当前卡片（去重取最新）
    cards = _load_jsonl(CARDS_FILE)
    seen = {}
    for c in reversed(cards):
        cid = c.get("id", "")
        if cid and cid not in seen:
            seen[cid] = c

    decayed = []
    new_cards = 0
    missing_cards = 0
    for cid, c in seen.items():
        cur_ret = c.get("retention", 1.0)
        if cid not in baseline_cards:
            new_cards += 1
            continue
        base_ret = baseline_cards[cid]["retention"]
        if base_ret <= 0:
            continue
        drop = (base_ret - cur_ret) / base_ret
        if drop > 0.2:
            decayed.append({
                "id": cid,
                "baseline_retention": base_ret,
                "current_retention": cur_ret,
                "drop_pct": round(drop * 100, 1),
                "importance": c.get("importance", 0.5),
                "last_used_ts": c.get("last_used_ts", ""),
            })

    # 统计 baseline 中有但当前已消失的卡片
    missing_cards = len(baseline_cards) - (len(seen) - new_cards)

    decayed.sort(key=lambda x: x["drop_pct"], reverse=True)

    result = {
        "baseline_age_hours": round(age, 1),
        "baseline_saved_at": saved_at,
        "total_in_baseline": len(baseline_cards),
        "total_current": len(seen),
        "total_decayed": len(decayed),
        "total_new": new_cards,
        "total_missing": max(0, missing_cards),
        "decayed_cards": decayed,
    }
    return result


def signal(kind: str, card_id: str, context: str = ""):
    """记录使用信号，同时更新 Ebbinghaus 遗忘曲线 retention"""
    _append_jsonl(SIGNALS_FILE, {
        "ts": iso_now(),
        "kind": kind,
        "card_id": card_id,
        "context": context
    })
    # card_deprecated：更新卡片状态并标记废弃时间，不更新 retention
    if kind == "card_deprecated":
        cards = _load_jsonl(CARDS_FILE)
        for c in reversed(cards):
            if c.get("id") == card_id:
                _append_jsonl(CARDS_FILE, {
                    **c,
                    "status": "deprecated",
                    "deprecated_at": iso_now(),
                })
                break
        return
    # 更新卡片权重 + retention（Ebbinghaus 遗忘曲线）
    weight_inc = {"card_used": 0.3, "card_reinforced": 0.5, "card_recalled": 0.1}.get(kind, 0.1)
    retention_inc = {"card_used": 0.5, "card_reinforced": 0.5, "card_recalled": 0.3}.get(kind, 0.3)
    cards = _load_jsonl(CARDS_FILE)
    now = _dt.datetime.now(_dt.timezone.utc)
    for c in reversed(cards):
        if c.get("id") == card_id:
            decayed = _ebbinghaus_decay(c, now)
            new_retention = round(min(1.0, decayed + retention_inc), 4)
            new_w = round(c.get("weight", 1.0) + weight_inc, 2)
            new_importance = _calc_importance({**c, "weight": new_w, "retention": new_retention})
            _append_jsonl(CARDS_FILE, {
                **c,
                "weight": new_w,
                "last_used_ts": iso_now(),
                "retention": new_retention,
                "importance": new_importance,
            })
            break


def session_snapshot(events: List[Dict], task_summary: str = ""):
    """会话结束快照：持久化会话摘要"""
    session_id = _hash_id(f"{iso_now()}{task_summary}", "ses")
    snapshot = {
        "session_id": session_id,
        "ts": iso_now(),
        "task_summary": task_summary,
        "events": events,
    }
    _append_jsonl(SESSION_DIR / f"{_dt.datetime.now().strftime('%Y%m%d')}.jsonl", snapshot)
    return session_id


# ── 自动收割：启发式提取 ──────────────────────────────

# 关键词模式 — 匹配值得持久化的发现
DISCOVERY_PATTERNS = [
    (re.compile(r"(发现|注意|关键|重要|记住|规律|经验|教训|坑[：:点]?|踩坑|陷阱|gotcha|tip|note).{0,30}?[：:：]\s*(.+)"), "发现"),
    (re.compile(r"(问题|原因|根因|bug|error|错误|失败).{0,20}?(是|在于|由于|因为|出在)\s*(.+)"), "问题根因"),
    (re.compile(r"(解决|修复|fix|workaround|绕过|hack).{0,20}?[：:：]?\s*(.+)"), "解决方案"),
    (re.compile(r"(命令|command|cmd|cli|脚本).{0,10}?[：:：]?\s*(`.+?`|[\w\-./\\]+)", re.I), "命令/脚本"),
    (re.compile(r"(配置|config|设置|参数|param).{0,20}?[：:：]?\s*(.+)"), "配置/参数"),
    (re.compile(r"(文件|路径|path|file|目录).{0,10}?[：:：]?\s*([A-Za-z]:[^\s,，。]+)", re.I), "文件路径"),
    (re.compile(r"(流程|步骤|pipeline|workflow|pattern).{0,10}?[：:：]?\s*(.+)"), "流程/模式"),
    (re.compile(r"(不再|不要|禁止|避免|never|don't|avoid|should not)\s*(.+)"), "禁忌规则"),
]

# 关键动词 — 一句话是否是"值得记住的"
SIGNAL_VERBS = {"发现", "注意", "关键", "重要", "记住", "经验", "教训", "坑", "踩坑",
                "陷阱", "gotcha", "tip", "note", "问题", "原因", "解决", "修复",
                "禁止", "不要", "避免", "必须", "required", "配置", "设置"}


def harvest_from_text(text: str, auto_confirm: bool = False) -> List[Dict]:
    """
    从对话摘要文本中启发式提取候选知识卡片。

    输入：Agent 对本轮对话的摘要文本（中文/英文混排）
    输出：候选卡片列表，每项包含 title/when_to_use/problem/solution_steps 等字段
    """
    candidates = []
    lines = text.split("\n")

    # 按段落聚合上下文
    paragraphs = []
    current = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(" ".join(current))
                current = []
        else:
            current.append(stripped)
    if current:
        paragraphs.append(" ".join(current))

    for para in paragraphs:
        # 跳过过短的段落
        if len(para) < 10:
            continue

        # 检查是否包含信号动词
        has_signal = any(v in para for v in SIGNAL_VERBS)
        if not has_signal:
            continue

        # 尝试匹配模式
        for pattern, category in DISCOVERY_PATTERNS:
            m = pattern.search(para)
            if m:
                groups = m.groups()
                # 提取有效内容（取最后一个非空捕获组）
                content = ""
                for g in reversed(groups):
                    if g and len(g.strip()) > 3:
                        content = g.strip()
                        break
                if not content:
                    continue

                # 构建卡片
                title = f"{category}：{content[:60]}"
                if len(content) > 60:
                    title += "..."

                card = {
                    "title": title,
                    "when_to_use": _extract_when(para, category),
                    "problem": para[:200],
                    "solution_steps": [content],
                    "tags": _extract_tags(para),
                    "scope": "project",
                    "_source_category": category,
                    "_source_text": para[:300],
                }
                candidates.append(card)
                break  # 每个段落只匹配第一个成功模式

    # 去重：按 title 相似度
    unique = []
    seen_titles = set()
    for c in candidates:
        title_key = c["title"][:30]
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique.append(c)

    # 自动确认写入
    if auto_confirm:
        results = []
        for c in unique:
            r = record(
                title=c["title"],
                when_to_use=c["when_to_use"],
                problem=c["problem"],
                solution_steps=c["solution_steps"],
                tags=c["tags"],
                scope=c["scope"],
            )
            results.append({"candidate": c["title"][:50], "result": r})
        return results

    return unique


def harvest_structured_from_text(text: str, auto_confirm: bool = False) -> List[Dict]:
    """
    从 LLM 预处理的结构化文本中直接提取知识卡片，跳过正则匹配。

    输入格式（agent 输出，## 卡片 分隔）：
        ## 卡片1
        标题: <title>
        何时使用: <when_to_use>
        问题: <problem>
        解决方案: <solution>
        标签: <tag1>, <tag2>

    输出：record() 的结果列表（auto_confirm=True）或候选卡片列表（auto_confirm=False）
    """
    cards = []
    # 按 "## " 分割卡片块
    blocks = re.split(r"\n##\s+", "\n" + text)
    for block in blocks:
        if not block.strip():
            continue
        # 跳过非卡片块（如 "## 总结" 等）
        if not re.match(r"(卡片|经验|知识|记忆)", block.split("\n")[0].strip()):
            continue

        card = _parse_structured_card(block)
        if card:
            cards.append(card)

    if auto_confirm:
        results = []
        for c in cards:
            r = record(
                title=c["title"],
                when_to_use=c["when_to_use"],
                problem=c["problem"],
                solution_steps=c["solution_steps"],
                tags=c["tags"],
                scope=c.get("scope", "project"),
            )
            results.append({"title": c["title"][:60], "result": r})
        return results

    return cards


def _parse_structured_card(block: str) -> Optional[Dict]:
    """解析单个结构化卡片块，返回 card dict 或 None"""
    lines = block.strip().split("\n")
    # 第一行是标题行（如 "卡片1" 或 "经验2"），跳过

    fields: Dict[str, Any] = {
        "title": "",
        "when_to_use": "",
        "problem": "",
        "solution_steps": [],
        "tags": [],
        "scope": "project",
    }

    current_field = None
    buffer = []

    for line in lines[1:]:  # 跳过标题行
        stripped = line.strip()
        m = re.match(r"^(标题|何时使用|问题|解决方案|标签)\s*[:：]\s*(.*)", stripped)
        if m:
            # 保存上一个字段
            if current_field and buffer:
                _set_card_field(fields, current_field, buffer)
                buffer = []
            current_field = m.group(1)
            value = m.group(2).strip()
            if value:
                buffer.append(value)
        elif stripped:
            # 续行，追加到当前字段
            buffer.append(stripped)

    # 保存最后一个字段
    if current_field and buffer:
        _set_card_field(fields, current_field, buffer)

    if not fields["title"]:
        return None

    return fields


def _set_card_field(card: Dict, field: str, lines: List[str]) -> None:
    """将多行 buffer 写入 card 对应字段"""
    text = " ".join(lines).strip()
    field_key = {
        "标题": "title",
        "何时使用": "when_to_use",
        "问题": "problem",
        "解决方案": "solution_steps",
        "标签": "tags",
    }.get(field)

    if field_key == "title":
        card["title"] = text
    elif field_key == "when_to_use":
        card["when_to_use"] = text
    elif field_key == "problem":
        card["problem"] = text
    elif field_key == "solution_steps":
        # 解决方案支持多行，每行一个步骤
        card["solution_steps"] = lines
    elif field_key == "tags":
        # 按逗号或顿号或空格拆分
        tags = re.split(r"[,，、\s]+", text)
        card["tags"] = [t.strip() for t in tags if t.strip()][:8]


def _extract_when(text: str, category: str) -> str:
    """从文本推断触发条件"""
    when_map = {
        "发现": "遇到类似场景时",
        "问题根因": "出现相同错误/异常时",
        "解决方案": "需要修复同类问题时",
        "命令/脚本": "执行相关操作时",
        "配置/参数": "配置相关服务时",
        "文件路径": "查找相关文件时",
        "流程/模式": "执行相似任务时",
        "禁忌规则": "可能触发同类错误时",
    }
    # 尝试从原文提取更具体的触发条件
    m = re.search(r"(当|遇到|出现|执行|配置|使用).{0,30}?(时|的时候)", text)
    if m:
        return m.group(0)
    return when_map.get(category, "相关场景")


def _extract_tags(text: str) -> List[str]:
    """从文本提取关键词作为标签"""
    tags = []
    # 文件扩展名
    exts = set(re.findall(r"\.([a-z]{2,5})\b", text.lower()))
    tags.extend([f"ext:{e}" for e in exts if e not in {"com", "org", "net", "txt", "md"}])

    # 技术关键词
    tech_keywords = {
        "docker": "docker", "git": "git", "api": "api", "json": "json",
        "yaml": "yaml", "python": "python", "powershell": "powershell",
        "ssh": "ssh", "http": "http", "proxy": "proxy", "代理": "proxy",
        "数据库": "database", "定时任务": "scheduler", "记忆": "memory",
        "索引": "index", "alist": "alist", "pepe": "pepe-arena",
        "macd": "macd", "rsi": "rsi", "adx": "adx", "交易": "trading",
        "信号": "signal", "策略": "strategy", "配置": "config",
        "编码": "encoding", "编码损坏": "encoding",
    }
    for kw, tag in tech_keywords.items():
        if kw in text.lower():
            tags.append(tag)

    return tags[:8]


def session_list(days: int = 7) -> List[Dict]:
    """列出最近的会话快照"""
    snapshots = []
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)
    if not SESSION_DIR.exists():
        return []
    for f in sorted(SESSION_DIR.glob("*.jsonl"), reverse=True):
        items = _load_jsonl(f)
        for item in items:
            ts = item.get("ts", "")
            try:
                dt = _ts_to_dt(ts)
            except Exception:
                continue
            if dt >= cutoff:
                snapshots.append(item)
    return snapshots


def review(days: int = 7, query: str = "", tags: List[str] = None, status: str = None):
    """回顾面板"""
    cards = _load_jsonl(CARDS_FILE)
    # 去重取最新
    latest: Dict[str, Dict] = {}
    for c in cards:
        cid = c.get("id", "")
        if cid:
            latest[cid] = c

    now = _dt.datetime.now(_dt.timezone.utc)
    results = []
    for cid, c in latest.items():
        if status and c.get("status") != status:
            continue
        ts = c.get("ts", iso_now())
        try:
            age_days = (now - _ts_to_dt(ts)).days
        except Exception:
            age_days = 0
        if age_days > days:
            continue
        # 计算当前有效权重（含衰减）
        decay = 0.5 ** (age_days / 30.0)
        eff_weight = c.get("weight", 1.0) * decay
        results.append({**c, "_age_days": age_days, "_eff_weight": round(eff_weight, 3)})

    if query:
        # TF-IDF 辅助排序
        idx = TfidfIndex().load()
        tfidf_hits = dict(idx.search(query, top_k=200))
        for r in results:
            r["_score"] = r["_eff_weight"] + tfidf_hits.get(r["id"], 0)
        results.sort(key=lambda x: -x["_score"])
    else:
        results.sort(key=lambda x: -x["_eff_weight"])

    if tags:
        tag_set = set(tags)
        results = [r for r in results if tag_set & set(r.get("tags", []))]

    return results


def dedup(threshold: float = 0.45) -> List[Dict]:
    """
    全文语义相似度去重检测。
    使用 TF-IDF 索引对所有卡片做 pairwise 余弦相似度比对，
    返回超过阈值的相似对及其相似度得分。
    """
    idx = TfidfIndex().load()
    if not idx.documents:
        return []

    cards = _load_jsonl(CARDS_FILE)
    # 取每个 ID 的最新版本
    latest: Dict[str, Dict] = {}
    for c in cards:
        cid = c.get("id", "")
        if cid and c.get("status") != "deprecated":
            latest[cid] = c

    doc_ids = [cid for cid in latest if cid in idx.documents]
    n = len(doc_ids)
    if n < 2:
        return []

    # 预计算所有文档的 TF-IDF 向量和模长
    vectors = {}
    norms = {}
    for cid in doc_ids:
        doc = idx.documents[cid]
        weights = doc.get("weights", {})
        vec = {}
        sq_sum = 0.0
        for token, tf in weights.items():
            idf_val = idx.idf.get(token, 1.0)
            w = tf * idf_val
            vec[token] = w
            sq_sum += w ** 2
        vectors[cid] = vec
        norms[cid] = math.sqrt(sq_sum)

    # pairwise 余弦相似度
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            cid_a, cid_b = doc_ids[i], doc_ids[j]
            va, vb = vectors[cid_a], vectors[cid_b]
            # 取交集 token 计算点积
            if len(va) > len(vb):
                va, vb = vb, va
            dot = 0.0
            for token, wa in va.items():
                wb = vb.get(token, 0.0)
                dot += wa * wb
            na, nb = norms[cid_a], norms[cid_b]
            cos_sim = dot / (na * nb) if na > 0 and nb > 0 else 0.0

            if cos_sim >= threshold:
                ca = latest[cid_a]
                cb = latest[cid_b]
                pairs.append({
                    "card_a": {"id": cid_a, "title": ca.get("title", ""),
                               "tags": ca.get("tags", []), "status": ca.get("status", "")},
                    "card_b": {"id": cid_b, "title": cb.get("title", ""),
                               "tags": cb.get("tags", []), "status": cb.get("status", "")},
                    "similarity": round(cos_sim, 4),
                })

    pairs.sort(key=lambda x: -x["similarity"])
    return pairs


def compact() -> Dict:
    """紧凑化 cards.jsonl：去除重复 ID 行，仅保留每个 ID 的最新版本"""
    cards = _load_jsonl(CARDS_FILE)
    if not cards:
        return {"before": 0, "after": 0, "removed": 0}

    before = len(cards)
    latest: Dict[str, Dict] = {}
    for c in cards:
        cid = c.get("id", "")
        if cid:
            latest[cid] = c  # later writes overwrite earlier ones

    # 备份原文件
    backup_path = Path(str(CARDS_FILE) + ".bak")
    with open(CARDS_FILE, "r", encoding="utf-8", errors="replace") as src:
        with open(backup_path, "w", encoding="utf-8") as dst:
            dst.write(src.read())

    # 写入去重版本
    with open(CARDS_FILE, "w", encoding="utf-8") as f:
        for cid in sorted(latest.keys()):
            card = latest[cid]
            f.write(json.dumps(card, ensure_ascii=False) + "\n")

    after = len(latest)
    removed = before - after
    return {"before": before, "after": after, "removed": removed, "backup": str(backup_path)}


def check_index():
    """检查索引退化状态"""
    cards = _load_jsonl(CARDS_FILE)
    active_cards = [c for c in cards if c.get("status") != "deprecated"]
    card_count = sum(1 for c in cards if c.get("id", ""))
    meta = _read_json(INDEX_META_FILE) if INDEX_META_FILE.exists() else {}
    last_build_ts = meta.get("last_build_ts")
    card_count_at_build = meta.get("card_count", 0)

    now = _dt.datetime.now(_dt.timezone.utc)
    age_days = None
    if last_build_ts:
        try:
            age = now - _ts_to_dt(last_build_ts)
            age_days = age.total_seconds() / 86400
        except Exception:
            age_days = None

    index_exists = INDEX_FILE.exists()

    reasons = []
    if not index_exists:
        reasons.append("索引文件不存在")
    elif age_days is not None and age_days > 30:
        reasons.append(f"索引距今 {age_days:.0f} 天（> 30 天阈值）")
    if card_count_at_build > 0 and card_count > card_count_at_build * 1.2:
        reasons.append(f"卡片数 {card_count} > 构建时 {card_count_at_build}（+{card_count - card_count_at_build}，超过 20% 阈值）")

    needs_rebuild = len(reasons) > 0

    return {
        "index_exists": index_exists,
        "age_days": round(age_days, 1) if age_days is not None else None,
        "card_count": card_count,
        "card_count_at_build": card_count_at_build,
        "needs_rebuild": needs_rebuild,
        "reasons": reasons,
    }


def build_index(auto: bool = False):
    """全量重建索引（TF-IDF + 向量）"""
    if auto:
        status = check_index()
        if not status["needs_rebuild"]:
            return {"action": "skipped", "reason": "索引健康，无需重建", "check": status}

    cards = _load_jsonl(CARDS_FILE)
    latest: Dict[str, Dict] = {}
    for c in cards:
        cid = c.get("id", "")
        if cid:
            latest[cid] = c

    # TF-IDF 索引
    idx = TfidfIndex()
    for cid, c in latest.items():
        if c.get("status") == "deprecated":
            continue
        text = f"{c.get('title','')} {c.get('when_to_use','')} {c.get('problem','')} {' '.join(c.get('tags',[]))}"
        idx.add(cid, text, weight=c.get("weight", 1.0))
    idx.save()

    # 向量索引
    vidx = VectorIndex()
    active_cards = [c for c in latest.values() if c.get("status") != "deprecated"]
    n_vec = vidx.rebuild_from_cards(active_cards)

    # 保存元数据
    meta = {
        "last_build_ts": iso_now(),
        "card_count": len(latest),
        "active_count": len(active_cards),
        "tfidf_docs": len(idx.documents),
        "vector_docs": n_vec,
    }
    _write_json(INDEX_META_FILE, meta)

    return {"tfidf_docs": len(idx.documents), "vector_docs": n_vec}


def migrate_from_selflearning():
    """从旧 self-learning-skills 迁移数据"""
    old_store = Path("D:/hi/.agents/memory/self-learning/v1/users/hi")
    if not old_store.exists():
        return {"error": "旧存储不存在", "path": str(old_store)}

    old_cards = _load_jsonl(old_store / "aha_cards.jsonl")
    migrated = 0
    skipped = 0

    for c in old_cards:
        cid = c.get("id", "")
        title = c.get("title", "")
        if not title or not cid:
            skipped += 1
            continue

        # 转换格式（修复旧数据中可能存在的编码损坏）
        new_card = {
            "id": cid,
            "ts": c.get("ts", iso_now()),
            "title": _repair_encoding(title),
            "when_to_use": _repair_encoding(c.get("when_to_use", "")),
            "problem": _repair_encoding(c.get("problem", "")),
            "solution_steps": [_repair_encoding(s) for s in (c.get("solution_steps") or [])],
            "evidence": [_repair_encoding(s) for s in (c.get("evidence") or [])],
            "tags": [_repair_encoding(s) for s in (c.get("tags") or [])],
            "gotchas": [_repair_encoding(s) for s in (c.get("gotchas") or [])],
            "scope": c.get("scope", "project"),
            "weight": 1.0,
            "reinforced_count": 0,
            "status": c.get("status", "active"),
            "_migrated_from": "self-learning-v1"
        }
        _append_jsonl(CARDS_FILE, new_card)
        migrated += 1
        # 内容不为空的卡片自动写信号
        if title or c.get("problem") or c.get("solution_steps"):
            signal("card_recorded", cid, context=title[:80])

    # 迁移推荐
    old_recs = _load_jsonl(old_store / "recommendations.jsonl")
    for r in old_recs:
        rid = r.get("id", "")
        if not rid:
            continue
        new_rec = {
            "id": rid,
            "ts": r.get("ts", iso_now()),
            "title": r.get("title", ""),
            "why": r.get("why", ""),
            "impact": r.get("expected_impact", {}),
            "hint": r.get("implementation_hint", ""),
            "tags": r.get("tags", []),
            "scope": r.get("scope", "project"),
            "status": r.get("status", "proposed"),
            "_migrated_from": "self-learning-v1"
        }
        _append_jsonl(RECS_FILE, new_rec)

    # 建索引
    n_indexed = build_index()

    return {"migrated_cards": migrated, "skipped": skipped, "indexed": n_indexed}


# ══════════════════════════════════════════════════════
# P3: 轻量版「炼知识」— 聚类合成 / 跨卡关联 / 信号分析 / 成熟度评分
# ══════════════════════════════════════════════════════

def _get_active_cards() -> Dict[str, Dict]:
    """获取所有活跃卡片（最新版本，排除 deprecated 和已合成卡片）"""
    cards = _load_jsonl(CARDS_FILE)
    latest: Dict[str, Dict] = {}
    for c in cards:
        cid = c.get("id", "")
        if cid:
            latest[cid] = c
    return {cid: c for cid, c in latest.items()
            if c.get("status") not in ("deprecated", "synthesized")}


def synthesize(threshold: float = 0.6, min_cluster_size: int = 2,
               auto_write: bool = False) -> Dict:
    """聚类相似卡片并生成知识合成卡片。

    使用向量语义相似度对活跃卡片进行贪心聚类，
    对满足最小簇大小的簇生成一张合成卡片，包含合并的
    解决方案、标签和触发条件。源卡片标记为 synthesized 状态。

    返回: {"clusters": N, "synthesis_cards": [...]}
    """
    active = _get_active_cards()
    if len(active) < min_cluster_size:
        return {"clusters": 0, "synthesis_cards": [], "note": f"活跃卡片不足 ({len(active)} < {min_cluster_size})"}

    # 嵌入所有活跃卡片
    card_ids = list(active.keys())
    texts = [VectorIndex._build_text(active[cid]) for cid in card_ids]
    vidx = VectorIndex()
    vectors = vidx._embed(texts)

    # 计算余弦相似度矩阵
    sim_matrix = np.dot(vectors, vectors.T)

    # 贪心聚类：按 weight 降序，未聚类的卡片依次作为种子
    order = sorted(range(len(card_ids)), key=lambda i: -active[card_ids[i]].get("weight", 1.0))
    clustered: set = set()
    clusters: List[List[Tuple[str, float]]] = []

    for i in order:
        cid = card_ids[i]
        if cid in clustered:
            continue
        members: List[Tuple[str, float]] = [(cid, 1.0)]
        for j in range(len(card_ids)):
            if i == j:
                continue
            cid2 = card_ids[j]
            if cid2 in clustered:
                continue
            sim = float(sim_matrix[i, j])
            if sim >= threshold:
                members.append((cid2, sim))
        if len(members) >= min_cluster_size:
            clusters.append(members)
            for mid, _ in members:
                clustered.add(mid)

    synthesis_cards = []
    for members in clusters:
        source_ids = [m[0] for m in members]
        source_cards = [active[cid] for cid in source_ids]

        # 收集所有标签，规范化（修复逗号分隔字符串为一个标签的旧数据），取出现频率最高的
        all_tags: List[str] = []
        for c in source_cards:
            for t in c.get("tags", []):
                if isinstance(t, str) and "," in t and len(t) > 20:
                    # 修复旧数据：逗号分隔字符串 → 拆分为独立标签
                    all_tags.extend(part.strip() for part in t.split(",") if part.strip())
                else:
                    all_tags.append(t)
        tag_counter = Counter(all_tags)
        top_tags = [t for t, _ in tag_counter.most_common(5)]

        # 生成合成标题
        if top_tags:
            syn_title = "知识簇: " + ", ".join(top_tags[:3])
        else:
            syn_title = "知识合成: " + source_cards[0].get("title", "")[:40]
        if len(syn_title) > 80:
            syn_title = syn_title[:77] + "..."

        # 合并 when_to_use
        all_when = []
        for c in source_cards:
            w = c.get("when_to_use", "").strip()
            if w and w not in all_when:
                all_when.append(w)

        # 合并问题描述
        problems = []
        for c in source_cards:
            p = c.get("problem", "").strip()
            if p and p not in problems:
                problems.append(p)

        # 合并解决方案（去重）
        solutions: List[str] = []
        seen_sol = set()
        for c in source_cards:
            for s in c.get("solution_steps", []):
                key = s.strip()[:60]
                if key and key not in seen_sol:
                    seen_sol.add(key)
                    solutions.append(s.strip())

        # 收集证据
        evidence_all: List[str] = []
        for c in source_cards:
            for e in c.get("evidence", []):
                if e.strip() and e.strip() not in evidence_all:
                    evidence_all.append(e.strip())

        # 收集坑点
        gotchas_all: List[str] = []
        for c in source_cards:
            for g in c.get("gotchas", []):
                if g.strip() and g.strip() not in gotchas_all:
                    gotchas_all.append(g.strip())

        syn_card: Dict[str, Any] = {
            "title": syn_title,
            "when_to_use": " ; ".join(all_when[:3]),
            "problem": " ; ".join(problems[:5]),
            "solution_steps": solutions[:10],
            "evidence": evidence_all[:5],
            "tags": top_tags,
            "gotchas": gotchas_all[:5],
            "scope": source_cards[0].get("scope", "project"),
            "importance": max(c.get("importance", 0.5) for c in source_cards),
            "_synthesis_of": source_ids,
            "_source_count": len(source_ids),
            "status": "active",
        }

        synthesis_info = {
            "id": "",
            "title": syn_title,
            "source_count": len(source_ids),
            "source_ids": source_ids,
            "top_tags": top_tags,
        }

        if auto_write:
            syn_id = _hash_id(syn_title + "".join(sorted(source_ids)), "sm")
            syn_card["id"] = syn_id
            syn_card["weight"] = round(1.0 + math.log(len(source_ids) + 1), 3)
            syn_card["reinforced_count"] = 0
            _append_jsonl(CARDS_FILE, syn_card)
            synthesis_info["id"] = syn_id

            # 标记源卡片为已合成
            for cid in source_ids:
                updated = dict(active[cid])
                updated["status"] = "synthesized"
                updated["_synthesized_into"] = syn_id
                _append_jsonl(CARDS_FILE, updated)

            signal("card_recorded", syn_id, context=f"synthesized from {len(source_ids)} cards")

        synthesis_cards.append(synthesis_info)

    return {"clusters": len(clusters), "synthesis_cards": synthesis_cards}


def cross_link(threshold: float = 0.5, top_k: int = 3,
               auto_write: bool = False) -> Dict:
    """基于向量相似度发现跨卡片关联并建立双向链接。

    对每张活跃卡片找到 top_k 张最相似的非自身卡片，
    添加或更新 _related 字段（双向链接）。

    返回: {"new_links": N, "cards_affected": N, "links": [...]}
    """
    active = _get_active_cards()
    if len(active) < 2:
        return {"new_links": 0, "cards_affected": 0, "note": "活跃卡片不足"}

    card_ids = list(active.keys())
    texts = [VectorIndex._build_text(active[cid]) for cid in card_ids]
    vidx = VectorIndex()
    vectors = vidx._embed(texts)
    sim_matrix = np.dot(vectors, vectors.T)

    # 收集已有链接（避免重复）
    existing_links: Dict[str, set] = {}
    for cid, c in active.items():
        existing_links[cid] = set()
        for rel in c.get("_related", []):
            if isinstance(rel, dict):
                existing_links[cid].add(rel.get("id", ""))
            elif isinstance(rel, str):
                existing_links[cid].add(rel)
        # 合成关系也算已有链接
        if c.get("_synthesis_of"):
            for sid in c["_synthesis_of"]:
                existing_links[cid].add(sid)
        if c.get("_synthesized_into"):
            existing_links[cid].add(c["_synthesized_into"])

    # 为每张卡片找 top_k 最相似卡片
    new_links = 0
    cards_updated: Dict[str, Dict] = {}
    links_detail: List[Dict] = []

    for i, cid in enumerate(card_ids):
        # 取相似度最高的 top_k + 1 个（跳过自身）
        sims = [(j, float(sim_matrix[i, j])) for j in range(len(card_ids)) if i != j]
        sims.sort(key=lambda x: -x[1])
        top_sims = sims[:top_k]

        new_related = []
        for j, sim in top_sims:
            if sim < threshold:
                break
            target_id = card_ids[j]
            if target_id in existing_links.get(cid, set()):
                continue
            new_related.append({"id": target_id, "_similarity": round(sim, 4)})
            # 双向建立
            if target_id not in cards_updated:
                cards_updated[target_id] = dict(active[target_id])
            target_existing = cards_updated[target_id].setdefault("_related", [])
            target_existing_ids = {r.get("id", r) if isinstance(r, dict) else r for r in target_existing}
            if cid not in target_existing_ids:
                target_existing.append({"id": cid, "_similarity": round(sim, 4)})

        if new_related:
            if cid not in cards_updated:
                cards_updated[cid] = dict(active[cid])
            existing_rel = cards_updated[cid].get("_related", [])
            if isinstance(existing_rel, list):
                cards_updated[cid]["_related"] = existing_rel + new_related
            else:
                cards_updated[cid]["_related"] = new_related
            new_links += len(new_related)
            for nr in new_related:
                links_detail.append({
                    "from": cid, "to": nr["id"],
                    "similarity": nr["_similarity"],
                })

    if auto_write and cards_updated:
        for cid, updated in cards_updated.items():
            _append_jsonl(CARDS_FILE, updated)

    return {
        "new_links": new_links,
        "cards_affected": len(cards_updated),
        "links": links_detail,
    }


def calculate_maturity(card: Dict, signals_data: List[Dict],
                       days: int = 30) -> float:
    """计算单张卡片的知识成熟度评分 (0.0~1.0)。

    公式:
      signal_score (0.5): min(total_signals / 10, 1.0) 的信号活跃度
      completeness (0.3): 字段完整性评分
      importance  (0.2): 卡片重要性
    """
    cid = card.get("id", "")
    now = _dt.datetime.now(_dt.timezone.utc)

    # 信号活跃度
    total_signals = 0
    for s in signals_data:
        if s.get("card_id") != cid:
            continue
        try:
            st = _ts_to_dt(s.get("ts", ""))
            if (now - st).days <= days:
                total_signals += 1
        except Exception:
            continue
    signal_score = min(total_signals / 10.0, 1.0)

    # 字段完整性
    checks = [
        bool(card.get("problem", "").strip()),
        bool(card.get("solution_steps")),
        bool(card.get("evidence")),
        bool(card.get("gotchas")),
        bool(card.get("tags")),
    ]
    completeness = sum(checks) / len(checks)

    # 重要性
    importance = card.get("importance", 0.5)

    maturity = signal_score * 0.5 + completeness * 0.3 + importance * 0.2
    return round(min(maturity, 1.0), 4)


def signal_analysis(days: int = 30, auto_write: bool = False) -> Dict:
    """分析使用信号，更新卡片成熟度评分。

    加载最近 days 天内的所有信号，为每张活跃卡片计算成熟度评分，
    写入 cards.jsonl 的 maturity_score 字段。

    同时识别：
      - high_recall: 召回频繁的卡片（top 20%）
      - zero_recall: 从未被召回的卡片
      - rising: 最近 7 天有新增召回活动的卡片

    返回: 分析摘要
    """
    signals = _load_jsonl(SIGNALS_FILE)
    cards = _load_jsonl(CARDS_FILE)

    # 取最新版卡片
    latest: Dict[str, Dict] = {}
    for c in cards:
        cid = c.get("id", "")
        if cid:
            latest[cid] = c

    now = _dt.datetime.now(_dt.timezone.utc)

    # 计算每张活跃卡片的成熟度
    maturity_updates: Dict[str, float] = {}
    recall_counts: Dict[str, int] = {}

    for cid, c in latest.items():
        if c.get("status") in ("deprecated",):
            continue
        m = calculate_maturity(c, signals, days=days)
        maturity_updates[cid] = m

        # 统计召回次数
        cnt = 0
        for s in signals:
            if s.get("card_id") == cid and s.get("kind") == "card_recalled":
                try:
                    st = _ts_to_dt(s.get("ts", ""))
                    if (now - st).days <= days:
                        cnt += 1
                except Exception:
                    continue
        recall_counts[cid] = cnt

    # 识别分组
    if recall_counts:
        max_recall = max(recall_counts.values())
        high_threshold = max(max_recall * 0.3, 2)  # top 30% 或至少 2 次
    else:
        high_threshold = 2

    high_recall = [cid for cid, cnt in recall_counts.items() if cnt >= high_threshold]
    zero_recall = [cid for cid, cnt in recall_counts.items() if cnt == 0]
    # rising: 最近 7 天有召回
    rising = []
    for cid in recall_counts:
        recent = 0
        for s in signals:
            if s.get("card_id") == cid and s.get("kind") == "card_recalled":
                try:
                    st = _ts_to_dt(s.get("ts", ""))
                    if (now - st).days <= 7:
                        recent += 1
                except Exception:
                    continue
        if recent > 0 and recall_counts.get(cid, 0) <= recent * 2:
            rising.append(cid)

    # 写入
    if auto_write:
        for cid, m in maturity_updates.items():
            old_m = latest[cid].get("maturity_score", -1)
            if abs(old_m - m) >= 0.001:
                updated = dict(latest[cid])
                updated["maturity_score"] = m
                _append_jsonl(CARDS_FILE, updated)

    return {
        "cards_analyzed": len(maturity_updates),
        "maturity_avg": round(sum(maturity_updates.values()) / max(len(maturity_updates), 1), 4),
        "high_recall_count": len(high_recall),
        "zero_recall_count": len(zero_recall),
        "rising_count": len(rising),
        "high_recall_ids": high_recall[:20],
        "zero_recall_ids": zero_recall[:20],
        "rising_ids": rising[:20],
    }


def maturity_report(limit: int = 50) -> Dict:
    """生成知识成熟度报告。

    返回按成熟度评分排序的卡片列表，含评级。
    """
    cards = _load_jsonl(CARDS_FILE)
    latest: Dict[str, Dict] = {}
    for c in cards:
        cid = c.get("id", "")
        if cid and c.get("status") != "deprecated":
            latest[cid] = c

    signals = _load_jsonl(SIGNALS_FILE)
    now = _dt.datetime.now(_dt.timezone.utc)

    ranked = []
    for cid, c in latest.items():
        m_score = c.get("maturity_score", 0)
        if m_score == 0:
            m_score = calculate_maturity(c, signals)
        # 评级
        if m_score >= 0.7:
            grade = "A"
        elif m_score >= 0.5:
            grade = "B"
        elif m_score >= 0.3:
            grade = "C"
        else:
            grade = "D"

        # 计算年龄
        ts = c.get("ts", "")
        try:
            age = (now - _ts_to_dt(ts)).days
        except Exception:
            age = -1

        ranked.append({
            "id": cid,
            "title": c.get("title", "")[:60],
            "maturity": m_score,
            "grade": grade,
            "age_days": age,
            "tags": c.get("tags", [])[:5],
            "status": c.get("status", ""),
        })

    ranked.sort(key=lambda x: -x["maturity"])
    return {
        "total": len(ranked),
        "by_grade": {
            "A": sum(1 for r in ranked if r["grade"] == "A"),
            "B": sum(1 for r in ranked if r["grade"] == "B"),
            "C": sum(1 for r in ranked if r["grade"] == "C"),
            "D": sum(1 for r in ranked if r["grade"] == "D"),
        },
        "cards": ranked[:limit],
    }


# ── CLI ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="smart-memory CLI")
    sub = parser.add_subparsers(dest="command")

    # recall
    p_recall = sub.add_parser("recall", help="任务前召回相关记忆")
    p_recall.add_argument("--query", "-q", default="", help="搜索关键词")
    p_recall.add_argument("--tags", "-t", nargs="*", help="标签过滤")
    p_recall.add_argument("--top", type=int, default=10, help="返回数量")
    p_recall.add_argument("--days", type=int, default=30, help="时间范围（天）")
    p_recall.add_argument("--mode", default="hybrid", choices=["tfidf", "vector", "hybrid"], help="检索模式")
    p_recall.add_argument("--format", default="text", choices=["text", "json"])

    # record
    p_record = sub.add_parser("record", help="记录知识卡片")
    p_record.add_argument("--title", required=True)
    p_record.add_argument("--when", default="", help="触发条件")
    p_record.add_argument("--problem", default="", help="问题描述")
    p_record.add_argument("--solution", nargs="*", default=[], help="解决步骤")
    p_record.add_argument("--evidence", nargs="*", default=[], help="证据/来源")
    p_record.add_argument("--tags", nargs="*", default=[], help="标签")
    p_record.add_argument("--gotchas", nargs="*", default=[], help="坑点")
    p_record.add_argument("--scope", default="project")
    p_record.add_argument("--importance", type=float, default=0.5, help="重要性 (0.0~1.0), 影响遗忘曲线衰减速度")

    # signal
    p_signal = sub.add_parser("signal", help="记录使用信号")
    p_signal.add_argument("--kind", required=True)
    p_signal.add_argument("--card-id", required=True)
    p_signal.add_argument("--context", default="")

    # review
    p_review = sub.add_parser("review", help="回顾面板")
    p_review.add_argument("--days", type=int, default=7)
    p_review.add_argument("--query", "-q", default="")
    p_review.add_argument("--tags", nargs="*")
    p_review.add_argument("--status", default="")
    p_review.add_argument("--format", default="text", choices=["text", "json"])

    # session
    p_session = sub.add_parser("session", help="会话快照")
    p_session.add_argument("--summary", default="", help="任务摘要")

    # harvest
    p_harvest = sub.add_parser("harvest", help="从对话摘要自动提取知识卡片（启发式正则）")
    p_harvest.add_argument("--text", required=True, help="对话摘要文本")
    p_harvest.add_argument("--auto-confirm", action="store_true", help="直接写入（跳过审查）")

    # harvest-structured（方法1：LLM 预处理层）
    p_hs = sub.add_parser("harvest-structured", help="从 LLM 预提取的结构化文本中直接入库")
    p_hs.add_argument("--text", default="", help="结构化文本（## 卡片N 格式）")
    p_hs.add_argument("--file", default="", help="从文件读取结构化文本")
    p_hs.add_argument("--auto-confirm", action="store_true", help="直接写入（跳过审查）")

    # session-list
    p_sesslist = sub.add_parser("session-list", help="列出历史会话快照")
    p_sesslist.add_argument("--days", type=int, default=7)

    # build-index
    p_bi = sub.add_parser("build-index", help="全量重建索引")
    p_bi.add_argument("--auto", action="store_true", help="仅在索引退化时重建")

    # check-index
    sub.add_parser("check-index", help="检查索引健康状态")

    # compact
    sub.add_parser("compact", help="紧凑化 cards.jsonl，去除重复 ID 行")

    # dedup
    p_dedup = sub.add_parser("dedup", help="全文语义去重检测")
    p_dedup.add_argument("--threshold", type=float, default=0.45, help="相似度阈值 (0.0~1.0)")

    # migrate
    sub.add_parser("migrate", help="从 self-learning-skills 迁移")

    # recalc-importance
    p_recalc = sub.add_parser("recalc-importance", help="基于信号数据批量重算所有卡片的 importance")
    p_recalc.add_argument("--dry-run", action="store_true", help="仅预览，不写入")

    # recalc-decay
    p_decay = sub.add_parser("recalc-decay", help="批量更新所有卡片的 retention（遗忘曲线）和 importance")
    p_decay.add_argument("--dry-run", action="store_true", help="仅预览，不写入")
    p_decay.add_argument("--save-baseline", action="store_true", help="衰减前保存 retention 快照，供巡检对比")

    # decay-report
    p_dr = sub.add_parser("decay-report", help="对比 baseline 与当前 retention，输出衰减报告")

    # synthesize
    p_syn = sub.add_parser("synthesize", help="聚类相似卡片并生成知识合成卡片")
    p_syn.add_argument("--threshold", type=float, default=0.6, help="相似度阈值 (0.0~1.0)")
    p_syn.add_argument("--min-cluster-size", type=int, default=2, help="最小簇大小")
    p_syn.add_argument("--auto-write", action="store_true", help="自动写入结果")

    # cross-link
    p_xlink = sub.add_parser("cross-link", help="基于向量相似度发现跨卡片关联")
    p_xlink.add_argument("--threshold", type=float, default=0.5, help="关联相似度阈值")
    p_xlink.add_argument("--top-k", type=int, default=3, help="每张卡片最多关联数")
    p_xlink.add_argument("--auto-write", action="store_true", help="自动写入结果")

    # signal-analysis
    p_sig = sub.add_parser("signal-analysis", help="分析信号数据并更新成熟度评分")
    p_sig.add_argument("--days", type=int, default=30, help="分析时间范围（天）")
    p_sig.add_argument("--auto-write", action="store_true", help="自动写入 maturity_score")

    # maturity
    p_mat = sub.add_parser("maturity", help="知识成熟度报告")
    p_mat.add_argument("--limit", type=int, default=50, help="最多返回卡片数")

    args = parser.parse_args()

    if args.command == "recall":
        results = recall(query=args.query, tags=args.tags, top_k=args.top, days=args.days, mode=args.mode)
        if args.format == "json":
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print(f"\n── 记忆召回 (query='{args.query}', mode={args.mode}, top={len(results)}) ──\n")
            for i, r in enumerate(results, 1):
                print(f"  [{i}] [{r['_score']:.2f}] {r['title']}  ({r['id']})")
                print(f"      触发: {r.get('when_to_use','')[:60]}")
                if r.get('tags'):
                    print(f"      标签: {', '.join(r['tags'][:5])}")
                print()

    elif args.command == "record":
        result = record(
            title=args.title, when_to_use=args.when, problem=args.problem,
            solution_steps=args.solution, evidence=args.evidence,
            tags=args.tags, gotchas=args.gotchas, scope=args.scope,
            importance=args.importance,
        )
        print(json.dumps(result, ensure_ascii=False))

    elif args.command == "signal":
        signal(kind=args.kind, card_id=args.card_id, context=args.context)
        print(f"signal recorded: {args.kind} → {args.card_id}")

    elif args.command == "review":
        results = review(days=args.days, query=args.query, tags=args.tags, status=args.status)
        if args.format == "json":
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print(f"\n── 记忆回顾 (days={args.days}, {len(results)} 条) ──\n")
            if not results:
                print("  (无记录)")
            for i, r in enumerate(results, 1):
                w = r.get('_eff_weight', r.get('weight', 1))
                age = r.get('_age_days', '?')
                print(f"  [{i}] [w={w:.2f}, {age}d] {r['title']}  ({r['id']})")
                print(f"      状态: {r.get('status','?')}  触发: {r.get('when_to_use','')[:50]}")

    elif args.command == "session":
        sid = session_snapshot([], task_summary=args.summary)
        print(f"session snapshot: {sid}")

    elif args.command == "harvest":
        candidates = harvest_from_text(text=args.text, auto_confirm=args.auto_confirm)
        if args.auto_confirm:
            print(json.dumps(candidates, ensure_ascii=False, indent=2))
        else:
            print(f"\n── 收割候选 ({len(candidates)} 条) ──\n")
            if not candidates:
                print("  (未发现可提取的知识卡片)")
            for i, c in enumerate(candidates, 1):
                print(f"  [{i}] [{c['_source_category']}] {c['title']}")
                print(f"      触发: {c['when_to_use']}")
                print(f"      标签: {', '.join(c.get('tags', []))}")
                print(f"      原文: {c.get('_source_text', '')[:80]}...")
                print()

    elif args.command == "harvest-structured":
        text = args.text
        if args.file:
            with open(args.file, "r", encoding="utf-8") as f:
                text = f.read()
        if not text:
            print("错误: 需要提供 --text 或 --file")
            sys.exit(1)
        results = harvest_structured_from_text(text=text, auto_confirm=args.auto_confirm)
        if args.auto_confirm:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print(f"\n── 结构化收割候选 ({len(results)} 条) ──\n")
            if not results:
                print("  (未发现可提取的知识卡片)")
            for i, c in enumerate(results, 1):
                print(f"  [{i}] {c['title']}")
                print(f"      触发: {c['when_to_use']}")
                print(f"      标签: {', '.join(c.get('tags', []))}")
                print()

    elif args.command == "session-list":
        snaps = session_list(days=args.days)
        print(f"\n── 会话快照 (近{args.days}天, {len(snaps)} 条) ──\n")
        if not snaps:
            print("  (无记录)")
        for s in snaps:
            print(f"  [{s.get('session_id','?')}] {s.get('ts','?')}")
            print(f"      任务: {s.get('task_summary','')[:80]}")

    elif args.command == "build-index":
        n = build_index(auto=args.auto)
        if n.get("action") == "skipped":
            print(f"[skip] 索引无需重建: {n['reason']}")
        else:
            print(f"index rebuilt: TF-IDF={n['tfidf_docs']}, vector={n['vector_docs']} documents")

    elif args.command == "check-index":
        status = check_index()
        print(f"\n── 索引健康检查 ──")
        print(f"  索引文件: {'存在' if status['index_exists'] else '不存在'}")
        if status['age_days'] is not None:
            print(f"  索引年龄: {status['age_days']} 天")
        print(f"  当前卡片数: {status['card_count']}")
        print(f"  构建时卡片数: {status['card_count_at_build']}")
        if status['needs_rebuild']:
            print(f"  状态: ❌ 需要重建")
            for r in status['reasons']:
                print(f"    - {r}")
        else:
            print(f"  状态: ✓ 健康")

    elif args.command == "compact":
        result = compact()
        print(json.dumps(result, ensure_ascii=False))
        print(f"\ncompacted: {result['before']} → {result['after']} rows ({result['removed']} duplicates removed)")
        print(f"backup: {result['backup']}")

    elif args.command == "dedup":
        pairs = dedup(threshold=args.threshold)
        print(json.dumps(pairs, ensure_ascii=False, indent=2))
        print(f"\n共 {len(pairs)} 对相似记忆（阈值={args.threshold}）")

    elif args.command == "migrate":
        result = migrate_from_selflearning()
        print(json.dumps(result, ensure_ascii=False))

    elif args.command == "recalc-importance":
        cards = _load_jsonl(CARDS_FILE)
        seen = {}
        for c in reversed(cards):
            cid = c.get("id", "")
            if cid and cid not in seen:
                seen[cid] = c
        updated = []
        for cid, c in seen.items():
            old_imp = c.get("importance", 0.5)
            new_imp = _calc_importance(c)
            if abs(new_imp - old_imp) > 0.01:
                updated.append((cid, c.get("title", "")[:50], old_imp, new_imp))
                if not args.dry_run:
                    _append_jsonl(CARDS_FILE, {**c, "importance": new_imp})
        print(f"\n── 重算 importance ({len(updated)} 张卡片变更) ──\n")
        if not updated:
            print("  (所有卡片 importance 无需更新)")
        for cid, title, old, new in updated:
            print(f"  [{cid}] {title}")
            print(f"      {old:.2f} → {new:.2f}")
        if args.dry_run:
            print(f"\n[dry-run] 以上 {len(updated)} 张卡片未实际写入")

    elif args.command == "recalc-decay":
        result = batch_decay(dry_run=args.dry_run, save_baseline=args.save_baseline)
        print(f"\n── 批量衰减 ({result['total_cards']} 张卡片) ──\n")
        print(f"retention 更新: {result['retention_updated']} 张")
        print(f"importance 更新: {result['importance_updated']} 张")
        if result["retention_updated"] == 0 and result["importance_updated"] == 0:
            print("  (所有卡片保持最新，无需更新)")
        if args.save_baseline:
            print("baseline 已保存")
        if args.dry_run:
            print(f"\n[dry-run] 以上变更未实际写入")

    elif args.command == "decay-report":
        result = decay_report()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "synthesize":
        result = synthesize(threshold=args.threshold,
                            min_cluster_size=args.min_cluster_size,
                            auto_write=args.auto_write)
        print(json.dumps(result, ensure_ascii=False, indent=2) if result.get("synthesis_cards") else
              f"\n── 知识合成 ──\n{result.get('note', '')}")
        if result.get("synthesis_cards"):
            print(f"\n共发现 {result['clusters']} 个知识簇，{len(result['synthesis_cards'])} 张合成卡片：")
            for sc in result["synthesis_cards"]:
                print(f"  [{sc['id']}] {sc['title'][:60]}")
                print(f"      来源: {sc['source_count']} 张卡片 | 标签: {', '.join(sc['top_tags'][:3])}")
                if not args.auto_write:
                    print(f"      (预览模式，加 --auto-write 写入)")
                print()

    elif args.command == "cross-link":
        result = cross_link(threshold=args.threshold, top_k=args.top_k,
                            auto_write=args.auto_write)
        print(json.dumps(result, ensure_ascii=False, indent=2) if result.get("links") else
              f"\n── 跨卡关联 ──\n{result.get('note', '')}")
        if result.get("links"):
            print(f"\n新增 {result['new_links']} 条关联，涉及 {result['cards_affected']} 张卡片：")
            for link in result["links"][:20]:
                print(f"  {link['from'][:16]} ←→ {link['to'][:16]}  (sim={link['similarity']:.3f})")
            if len(result["links"]) > 20:
                print(f"  ... 共 {len(result['links'])} 条")
            if not args.auto_write:
                print(f"\n(预览模式，加 --auto-write 写入)")

    elif args.command == "signal-analysis":
        result = signal_analysis(days=args.days, auto_write=args.auto_write)
        print(f"\n── 信号分析 (days={args.days}) ──")
        print(f"分析卡片: {result['cards_analyzed']} 张")
        print(f"平均成熟度: {result['maturity_avg']:.2f}")
        print(f"高频召回: {result['high_recall_count']} 张")
        print(f"零召回:   {result['zero_recall_count']} 张")
        print(f"上升趋势: {result['rising_count']} 张")
        if not args.auto_write:
            print(f"\n(预览模式，加 --auto-write 写入 maturity_score)")

    elif args.command == "maturity":
        result = maturity_report(limit=args.limit)
        print(f"\n── 知识成熟度报告 (共 {result['total']} 张) ──")
        print(f"评级分布: A={result['by_grade']['A']}  B={result['by_grade']['B']}  "
              f"C={result['by_grade']['C']}  D={result['by_grade']['D']}")
        print()
        if not result["cards"]:
            print("  (无卡片)")
        for i, c in enumerate(result["cards"], 1):
            print(f"  [{i}] [{c['grade']}] [{c['maturity']:.2f}] {c['title'][:50]}")
            print(f"      年龄: {c['age_days']}d  |  标签: {', '.join(c['tags'][:3])}")
            print()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
