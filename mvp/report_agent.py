#!/usr/bin/env python3
"""
报告生成器 - 伪科普监测系统

输入：研判结果 JSONL
输出：结构化周报 Markdown
"""

import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime
from typing import Optional


def load_analysis(path: str) -> list[dict]:
    """加载研判结果"""
    results = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                results.append(json.loads(line))
    return results


def compute_stats(results: list[dict]) -> dict:
    """计算统计数据"""
    total = len(results)
    type_counts = Counter(r.get("content_type", "UNKNOWN") for r in results)
    severity_counts = Counter(r.get("severity", "NONE") for r in results)
    harm_counts = Counter(r.get("harm_line", "none") for r in results)

    # 伪科普条目
    pseudos = [r for r in results if r.get("content_type") == "PSEUDOSCIENCE"]

    # 按关键词分组
    keyword_groups = defaultdict(list)
    for r in results:
        kw = r.get("keyword", "未知")
        keyword_groups[kw].append(r)

    # 按危害主线分组
    harm_groups = defaultdict(list)
    for r in pseudos:
        harm = r.get("harm_line", "none")
        harm_groups[harm].append(r)

    return {
        "total": total,
        "type_counts": dict(type_counts),
        "severity_counts": dict(severity_counts),
        "harm_counts": dict(harm_counts),
        "pseudos": pseudos,
        "keyword_groups": dict(keyword_groups),
        "harm_groups": dict(harm_groups),
    }


def generate_report(
    results: list[dict],
    week_num: int = 0,
    start_date: str = "",
    end_date: str = "",
) -> str:
    """生成周报 Markdown"""
    stats = compute_stats(results)

    now = datetime.now()
    if not week_num:
        week_num = now.isocalendar()[1]
    if not start_date:
        start_date = (now - __import__("datetime").timedelta(days=7)).strftime("%Y-%m-%d")
    if not end_date:
        end_date = now.strftime("%Y-%m-%d")

    tc = stats["type_counts"]
    total = stats["total"]
    pseudo_count = tc.get("PSEUDOSCIENCE", 0)
    debunk_count = tc.get("DEBUNKING", 0)
    normal_count = tc.get("NORMAL_SCIENCE", 0)
    non_count = tc.get("NON_SCIENCE", 0)

    lines = [
        f"# 全网涉科谣言监测周报",
        f"",
        f"## 2026年第{week_num}周（{start_date}—{end_date}）",
        f"",
        f"> 自动生成 · 基于 v3 引擎研判结果",
        f"> 编制日期：{now.strftime('%Y-%m-%d')}",
        f"",
        f"---",
        f"",
        f"## 一、本周监测概况",
        f"",
        f"### 1.1 数据总览",
        f"",
        f"| 指标 | 本周数值 |",
        f"|------|----------|",
        f"| 采集总量 | {total}条 |",
        f"| AI研判覆盖率 | 100%（{total}/{total}） |",
        f"| 伪科普 | {pseudo_count}条（{pseudo_count/total*100:.1f}%） |",
        f"| 辟谣内容 | {debunk_count}条（{debunk_count/total*100:.1f}%） |",
        f"| 正常科普 | {normal_count}条（{normal_count/total*100:.1f}%） |",
        f"| 无关内容 | {non_count}条（{non_count/total*100:.1f}%） |",
        f"",
    ]

    # 1.2 危害主线分布
    hc = stats["harm_counts"]
    harm_labels = {
        "fraud": "电诈线",
        "reputation_attack": "风评受损线",
        "cult": "邪教属性线",
        "none": "未分类",
    }
    lines += [
        f"### 1.2 危害主线分布",
        f"",
        f"| 主线 | 数量 | 占比 |",
        f"|------|------|------|",
    ]
    for harm, count in sorted(hc.items(), key=lambda x: -x[1]):
        if harm != "none":
            pct = count / max(pseudo_count, 1) * 100
            lines.append(f"| {harm_labels.get(harm, harm)} | {count}条 | {pct:.0f}% |")
    if not any(h != "none" for h in hc):
        lines.append("| （无数据） | — | — |")
    lines.append("")

    # 1.3 关键词采集分布
    lines += [
        f"### 1.3 关键词采集分布",
        f"",
        f"| 关键词 | 采集量 | 伪科普 |",
        f"|--------|--------|--------|",
    ]
    for kw, items in sorted(stats["keyword_groups"].items(), key=lambda x: -len(x[1])):
        kw_pseudo = sum(1 for i in items if i.get("content_type") == "PSEUDOSCIENCE")
        lines.append(f"| {kw} | {len(items)}条 | {kw_pseudo}条 |")
    lines.append("")

    # 二、重点伪科普事件
    lines += [
        f"---",
        f"",
        f"## 二、重点伪科普事件",
        f"",
    ]

    # 按风险分排序，取 Top 5
    top_pseudos = sorted(stats["pseudos"], key=lambda x: -x.get("risk_score", 0))[:5]

    severity_icons = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "NONE": "⚪"}

    for i, p in enumerate(top_pseudos, 1):
        sev = p.get("severity", "MEDIUM")
        icon = severity_icons.get(sev, "⚪")
        harm = harm_labels.get(p.get("harm_line", "none"), "未分类")
        text = p.get("text", "") or p.get("content", "") or ""
        text = text[:150] if text else "（无摘要）"

        lines += [
            f"### {icon} 事件{i}",
            f"",
            f"| 项目 | 内容 |",
            f"|------|------|",
            f"| **发布者** | {p.get('username', '未知')} |",
            f"| **内容摘要** | {text} |",
            f"| **风险等级** | {sev} |",
            f"| **风险得分** | {p.get('risk_score', 0)} |",
            f"| **所属主线** | {harm} |",
            f"| **触发规则** | {', '.join(p.get('triggered_rules', []))} |",
            f"",
        ]

    # 三、趋势与建议
    lines += [
        f"---",
        f"",
        f"## 三、趋势与建议",
        f"",
        f"### 3.1 本周趋势",
        f"",
        f"- 伪科普占比：{pseudo_count/total*100:.1f}%",
        f"- 主要危害主线：{max(hc.items(), key=lambda x: x[1] if x[0] != 'none' else 0)[0] if hc else '无'}",
        f"",
        f"### 3.2 建议行动",
        f"",
        f"1. 重点监控高风险伪科普账号",
        f"2. 针对高频关键词制作辟谣内容",
        f"3. 关注危害主线趋势变化",
        f"",
    ]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="生成监测周报")
    parser.add_argument("input", help="研判结果 JSONL 文件路径")
    parser.add_argument("--output", "-o", help="输出文件路径", default="")
    parser.add_argument("--week", type=int, help="周数", default=0)
    parser.add_argument("--start", help="起始日期", default="")
    parser.add_argument("--end", help="结束日期", default="")

    args = parser.parse_args()

    results = load_analysis(args.input)
    print(f"加载 {len(results)} 条研判结果")

    report = generate_report(results, args.week, args.start, args.end)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"报告已保存到 {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
