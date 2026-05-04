#!/usr/bin/env python3
"""
传播分析器 - 伪科普监测系统

功能：
1. 跨平台内容相似度检测
2. 矩阵号识别（批量发相似内容的账号）
3. 传播链追踪
4. 时间模式分析
"""

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional


@dataclass
class ContentCluster:
    """相似内容聚类"""
    cluster_id: str
    representative_text: str
    entries: list[dict] = field(default_factory=list)
    platforms: set = field(default_factory=set)
    authors: set = field(default_factory=set)
    first_seen: str = ""
    last_seen: str = ""
    risk_score_max: float = 0.0
    content_type: str = ""


@dataclass
class MatrixAccount:
    """疑似矩阵号"""
    author: str
    author_id: str
    platform: str
    post_count: int = 0
    pseudo_count: int = 0
    clusters_joined: int = 0
    avg_similarity: float = 0.0
    risk_level: str = "LOW"
    evidence: list[str] = field(default_factory=list)


def normalize_text(text: str) -> str:
    """文本标准化：去除标点、空格、表情"""
    if not text:
        return ""
    # 去除URL
    text = re.sub(r'https?://\S+', '', text)
    # 去除@提及
    text = re.sub(r'@\S+', '', text)
    # 去除话题标签符号
    text = re.sub(r'#(\S+)#', r'\1', text)
    # 去除标点和空格
    text = re.sub(r'[^\u4e00-\u9fff\w]', '', text)
    return text.lower().strip()


def text_similarity(text1: str, text2: str) -> float:
    """计算两段文本的相似度（0-1）"""
    if not text1 or not text2:
        return 0.0
    # 标准化
    t1 = normalize_text(text1)
    t2 = normalize_text(text2)
    if not t1 or not t2:
        return 0.0
    # 完全相同
    if t1 == t2:
        return 1.0
    # 包含关系
    if t1 in t2 or t2 in t1:
        shorter = min(len(t1), len(t2))
        longer = max(len(t1), len(t2))
        if shorter > 10:  # 有意义的包含
            return shorter / longer * 0.9 + 0.1
    # SequenceMatcher
    return SequenceMatcher(None, t1, t2).ratio()


def cluster_content(entries: list[dict], threshold: float = 0.6) -> list[ContentCluster]:
    """将相似内容聚类"""
    clusters: list[ContentCluster] = []
    assigned = [False] * len(entries)

    for i, entry in enumerate(entries):
        if assigned[i]:
            continue
        text = entry.get("text", "") or entry.get("content", "")
        if not text:
            continue

        # 创建新聚类
        cluster = ContentCluster(
            cluster_id=f"C{len(clusters):04d}",
            representative_text=text[:200],
            entries=[entry],
            platforms={entry.get("platform", "unknown")},
            authors={entry.get("username", "") or entry.get("author", "")},
            first_seen=entry.get("publish_time", ""),
            last_seen=entry.get("publish_time", ""),
            risk_score_max=entry.get("risk_score", 0),
            content_type=entry.get("content_type", "UNKNOWN"),
        )
        assigned[i] = True

        # 查找相似内容
        for j in range(i + 1, len(entries)):
            if assigned[j]:
                continue
            other_text = entries[j].get("text", "") or entries[j].get("content", "")
            if not other_text:
                continue

            sim = text_similarity(text, other_text)
            if sim >= threshold:
                cluster.entries.append(entries[j])
                cluster.platforms.add(entries[j].get("platform", "unknown"))
                cluster.authors.add(entries[j].get("username", "") or entries[j].get("author", ""))
                assigned[j] = True

                # 更新时间范围
                pt = entries[j].get("publish_time", "")
                if pt and (not cluster.first_seen or pt < cluster.first_seen):
                    cluster.first_seen = pt
                if pt and pt > cluster.last_seen:
                    cluster.last_seen = pt

                # 更新风险分
                rs = entries[j].get("risk_score", 0)
                if rs > cluster.risk_score_max:
                    cluster.risk_score_max = rs

        clusters.append(cluster)

    return clusters


def detect_matrix_accounts(
    entries: list[dict],
    clusters: list[ContentCluster],
    min_posts: int = 3,
    min_cluster_ratio: float = 0.5,
) -> list[MatrixAccount]:
    """检测矩阵号：同一账号发布大量相似内容"""
    # 按账号分组
    account_entries = defaultdict(list)
    for entry in entries:
        author = entry.get("username", "") or entry.get("author", "")
        if author:
            account_entries[author].append(entry)

    # 建立 entry_id 到 cluster 的映射
    entry_cluster = {}
    for cluster in clusters:
        for entry in cluster.entries:
            eid = entry.get("content_id", "") or entry.get("weibo_id", "")
            if eid:
                entry_cluster[eid] = cluster.cluster_id

    matrix_accounts = []

    for author, posts in account_entries.items():
        if len(posts) < min_posts:
            continue

        platform = posts[0].get("platform", "unknown")
        author_id = posts[0].get("author_id", "") or posts[0].get("user_id", "")
        pseudo_count = sum(1 for p in posts if p.get("content_type") == "PSEUDOSCIENCE")

        # 计算该账号参与的聚类数
        clusters_joined = set()
        for p in posts:
            eid = p.get("content_id", "") or p.get("weibo_id", "")
            if eid in entry_cluster:
                clusters_joined.add(entry_cluster[eid])

        # 计算账号内内容相似度
        similarities = []
        texts = [normalize_text(p.get("text", "") or p.get("content", "")) for p in posts]
        texts = [t for t in texts if len(t) > 10]
        for i in range(len(texts)):
            for j in range(i + 1, len(texts)):
                similarities.append(text_similarity(texts[i], texts[j]))
        avg_sim = sum(similarities) / len(similarities) if similarities else 0

        # 判定风险等级
        risk_level = "LOW"
        evidence = []

        if len(posts) >= 5 and avg_sim > 0.7:
            risk_level = "HIGH"
            evidence.append(f"发布{len(posts)}条相似内容，平均相似度{avg_sim:.0%}")
        elif len(posts) >= 3 and avg_sim > 0.6:
            risk_level = "MEDIUM"
            evidence.append(f"发布{len(posts)}条内容，平均相似度{avg_sim:.0%}")

        if len(clusters_joined) >= 3:
            risk_level = "HIGH" if risk_level != "HIGH" else risk_level
            evidence.append(f"参与{len(clusters_joined)}个内容聚类")

        if pseudo_count >= 3:
            evidence.append(f"其中{pseudo_count}条被判定为伪科普")

        if risk_level != "LOW":
            ma = MatrixAccount(
                author=author,
                author_id=author_id,
                platform=platform,
                post_count=len(posts),
                pseudo_count=pseudo_count,
                clusters_joined=len(clusters_joined),
                avg_similarity=avg_sim,
                risk_level=risk_level,
                evidence=evidence,
            )
            matrix_accounts.append(ma)

    return sorted(matrix_accounts, key=lambda x: (-x.pseudo_count, -x.avg_similarity))


def analyze_propagation_patterns(clusters: list[ContentCluster]) -> dict:
    """分析传播模式"""
    patterns = {
        "cross_platform_count": 0,
        "multi_author_count": 0,
        "rapid_spread": [],
        "dominant_types": Counter(),
    }

    for cluster in clusters:
        if len(cluster.platforms) > 1:
            patterns["cross_platform_count"] += 1
        if len(cluster.authors) > 2:
            patterns["multi_author_count"] += 1
        if len(cluster.entries) >= 3:
            patterns["rapid_spread"].append({
                "cluster_id": cluster.cluster_id,
                "count": len(cluster.entries),
                "platforms": list(cluster.platforms),
                "authors": len(cluster.authors),
                "text_preview": cluster.representative_text[:100],
            })
        patterns["dominant_types"][cluster.content_type] += 1

    return patterns


def generate_propagation_report(
    entries: list[dict],
    clusters: list[ContentCluster],
    matrix_accounts: list[MatrixAccount],
    patterns: dict,
) -> str:
    """生成传播分析报告"""
    lines = [
        "# 传播分析报告",
        "",
        f"> 分析条目：{len(entries)}条",
        f"> 生成时间：{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "---",
        "",
        "## 一、内容聚类概览",
        "",
        f"- 总聚类数：{len(clusters)}",
        f"- 跨平台聚类：{patterns['cross_platform_count']}个",
        f"- 多账号传播：{patterns['multi_author_count']}个",
        f"- 快速传播（>=3条）：{len(patterns['rapid_spread'])}个",
        "",
    ]

    # 聚类类型分布
    lines += [
        "### 聚类内容类型分布",
        "",
        "| 类型 | 聚类数 |",
        "|------|--------|",
    ]
    for ct, count in patterns["dominant_types"].most_common():
        lines.append(f"| {ct} | {count} |")
    lines.append("")

    # 重点聚类
    significant = [c for c in clusters if len(c.entries) >= 3]
    if significant:
        lines += [
            "---",
            "",
            "## 二、重点传播聚类",
            "",
        ]
        for cluster in sorted(significant, key=lambda x: -len(x.entries))[:10]:
            lines += [
                f"### 聚类 {cluster.cluster_id}",
                "",
                f"| 项目 | 内容 |",
                f"|------|------|",
                f"| **传播条数** | {len(cluster.entries)}条 |",
                f"| **涉及平台** | {', '.join(cluster.platforms)} |",
                f"| **涉及账号** | {len(cluster.authors)}个 |",
                f"| **内容类型** | {cluster.content_type} |",
                f"| **最高风险分** | {cluster.risk_score_max:.2f} |",
                f"| **内容摘要** | {cluster.representative_text[:100]} |",
                "",
            ]

    # 矩阵号
    if matrix_accounts:
        lines += [
            "---",
            "",
            "## 三、疑似矩阵号",
            "",
        ]
        for i, ma in enumerate(matrix_accounts[:10], 1):
            lines += [
                f"### {i}. {ma.author}（{ma.platform}）",
                "",
                f"- **风险等级**：{ma.risk_level}",
                f"- **发布条数**：{ma.post_count}",
                f"- **伪科普条数**：{ma.pseudo_count}",
                f"- **参与聚类**：{ma.clusters_joined}个",
                f"- **内容相似度**：{ma.avg_similarity:.0%}",
                f"- **证据**：{'; '.join(ma.evidence)}",
                "",
            ]
    else:
        lines += [
            "---",
            "",
            "## 三、疑似矩阵号",
            "",
            "未检测到明显矩阵号。",
            "",
        ]

    return "\n".join(lines)


def load_entries(paths: list[str]) -> list[dict]:
    """从多个JSONL文件加载条目"""
    entries = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line))
    return entries


def main():
    parser = argparse.ArgumentParser(description="传播分析器")
    parser.add_argument("inputs", nargs="+", help="JSONL文件路径（可多个）")
    parser.add_argument("--threshold", type=float, default=0.6, help="相似度阈值（默认0.6）")
    parser.add_argument("--output", "-o", help="输出报告路径")
    parser.add_argument("--json", action="store_true", help="输出JSON格式")

    args = parser.parse_args()

    entries = load_entries(args.inputs)
    print(f"加载 {len(entries)} 条数据")

    # 内容聚类
    clusters = cluster_content(entries, args.threshold)
    print(f"发现 {len(clusters)} 个内容聚类")

    # 矩阵号检测
    matrix_accounts = detect_matrix_accounts(entries, clusters)
    print(f"发现 {len(matrix_accounts)} 个疑似矩阵号")

    # 传播模式分析
    patterns = analyze_propagation_patterns(clusters)

    if args.json:
        result = {
            "total_entries": len(entries),
            "clusters": len(clusters),
            "matrix_accounts": len(matrix_accounts),
            "patterns": {k: v for k, v in patterns.items() if k != "dominant_types"},
            "dominant_types": dict(patterns["dominant_types"]),
            "significant_clusters": [
                {
                    "id": c.cluster_id,
                    "count": len(c.entries),
                    "platforms": list(c.platforms),
                    "authors": len(c.authors),
                }
                for c in clusters
                if len(c.entries) >= 2
            ],
            "matrix_details": [
                {
                    "author": m.author,
                    "platform": m.platform,
                    "risk": m.risk_level,
                    "posts": m.post_count,
                    "pseudos": m.pseudo_count,
                }
                for m in matrix_accounts
            ],
        }
        output = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        output = generate_propagation_report(entries, clusters, matrix_accounts, patterns)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"报告已保存到 {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
