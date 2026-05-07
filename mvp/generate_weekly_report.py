#!/usr/bin/env python3
"""周报自动生成 — 从 analysis jsonl 提取统计 + 分析，输出 Markdown 周报."""

import json, sys, os
from datetime import datetime, timedelta
from collections import Counter, defaultdict

def load_data(jsonl_path):
    records = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            a = d.get("analysis", {})
            flat = {
                "username": d.get("username", ""),
                "text": d.get("text", ""),
                "publish_time": d.get("publish_time", ""),
                "reposts_count": d.get("reposts_count", 0),
                "comments_count": d.get("comments_count", 0),
                "attitudes_count": d.get("attitudes_count", 0),
                "followers_count": d.get("followers_count", 0),
                "verified": d.get("verified", False),
                "keyword": d.get("keyword", ""),
                "source_url": d.get("source_url", ""),
                "content_type": a.get("content_type", "NON_SCIENCE"),
                "severity": a.get("severity", "NONE"),
                "risk_score": a.get("risk_score", 0),
                "harm_line": a.get("harm_line", "none"),
                "harm_evidence": a.get("harm_evidence", []),
                "triggered_rules": a.get("triggered_rules", []),
                "llm_analysis": a.get("llm_analysis"),
                "llm_flipped": a.get("llm_flipped", False),
            }
            records.append(flat)
    return records

def classify_topic(text, keyword):
    """简单话题归类"""
    topics = {
        "疫苗": ["疫苗", "接种", "免疫"],
        "排毒": ["排毒", "毒素", "清肠", "肝胆排"],
        "致癌": ["致癌", "致癌物", "致癌食物", "一类致癌"],
        "量子": ["量子", "量子力学", "量子纠缠"],
        "干细胞": ["干细胞", "再生医学"],
        "中医/经络": ["经络", "气血", "肝经", "拍八虚", "倪师", "五脏排毒", "湿气", "阳虚"],
        "辐射": ["辐射", "电磁波", "信号塔"],
        "酸碱": ["酸性体质", "碱性体质", "碱性食物"],
        "能量": ["能量", "正能量", "负能量", "磁场"],
        "食品相克": ["相克", "不能同食", "搭配禁忌"],
    }
    combined = f"{text} {keyword}"
    for topic, kws in topics.items():
        for kw in kws:
            if kw in combined:
                return topic
    return "其他"

def weekly_report(jsonl_path, output_path=None):
    records = load_data(jsonl_path)
    now = datetime.now()
    week_start = now - timedelta(days=7)
    
    # 基本统计
    total = len(records)
    ct_counts = Counter(r["content_type"] for r in records)
    pseudo = [r for r in records if r["content_type"] == "PSEUDOSCIENCE"]
    debunk = [r for r in records if r["content_type"] == "DEBUNKING"]
    normal = [r for r in records if r["content_type"] == "NORMAL_SCIENCE"]
    nonsci = [r for r in records if r["content_type"] == "NON_SCIENCE"]
    
    sev_counts = Counter(r["severity"] for r in pseudo)
    
    # 危害主线
    harm_counts = Counter(r["harm_line"] for r in pseudo if r["harm_line"] != "none")
    
    # 话题聚类
    topic_counts = Counter()
    topic_severity = defaultdict(lambda: {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0})
    for r in pseudo:
        topic = classify_topic(r["text"], r["keyword"])
        topic_counts[topic] += 1
        topic_severity[topic][r["severity"]] += 1
    
    # 信源分析
    verified_pseudo = sum(1 for r in pseudo if r["verified"])
    high_fan_pseudo = sum(1 for r in pseudo if r["followers_count"] > 100000)
    
    # 传播量 top
    def spread(r):
        return r["reposts_count"] + r["comments_count"] + r["attitudes_count"]
    
    top_spread = sorted(pseudo, key=spread, reverse=True)[:5]
    top_risk = sorted(pseudo, key=lambda r: r["risk_score"], reverse=True)[:5]
    
    # LLM 调用统计
    llm_called = sum(1 for r in records if r["llm_analysis"] is not None)
    llm_flipped = sum(1 for r in records if r["llm_flipped"])
    
    # ── 生成 Markdown ──
    lines = []
    lines.append(f"# 伪科普监测周报")
    lines.append(f"**生成时间**: {now.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**数据范围**: {total} 条微博 · 采集于 2026-05-06")
    lines.append("")
    
    # 一、概览
    lines.append("## 一、本周概览")
    lines.append("")
    lines.append("| 分类 | 数量 | 占比 |")
    lines.append("|------|------|------|")
    for ct, label in [("PSEUDOSCIENCE", "🔴 伪科普/谣言"), ("DEBUNKING", "🟢 辟谣"), ("NORMAL_SCIENCE", "🔵 正常科普"), ("NON_SCIENCE", "⚪ 非科学")]:
        c = ct_counts.get(ct, 0)
        lines.append(f"| {label} | **{c}** | {c/total*100:.1f}% |")
    lines.append("")
    
    lines.append(f"- LLM 调用率: {llm_called}/{total} ({llm_called/total*100:.1f}%)")
    lines.append(f"- LLM 翻转规则引擎判断: {llm_flipped} 次")
    lines.append("")
    
    # 二、伪科普分析
    lines.append("## 二、伪科普/谣言分析（{} 条）".format(len(pseudo)))
    lines.append("")
    
    lines.append("### 严重度分布")
    lines.append("")
    lines.append("| 等级 | 数量 | 占比 |")
    lines.append("|------|------|------|")
    for sev in ["CRITICAL", "HIGH", "MEDIUM", "NONE"]:
        c = sev_counts.get(sev, 0)
        lines.append(f"| {sev} | **{c}** | {c/len(pseudo)*100:.1f}% |")
    lines.append("")
    
    if harm_counts:
        lines.append("### 危害主线")
        lines.append("")
        lines.append("| 危害类型 | 数量 |")
        lines.append("|----------|------|")
        harm_labels = {"fraud": "欺诈（虚假产品/疗法）", "reputation": "风评攻击（抹黑科学）", "cult": "邪教属性（极端崇拜/反智）"}
        for h, c in harm_counts.most_common():
            lines.append(f"| {harm_labels.get(h, h)} | **{c}** |")
        lines.append("")
    
    # 三、话题热度
    lines.append("## 三、谣言话题热度 Top 10")
    lines.append("")
    lines.append("| 话题 | 条数 | CRITICAL | HIGH | MEDIUM |")
    lines.append("|------|------|----------|------|--------|")
    for topic, cnt in topic_counts.most_common(10):
        sev = topic_severity[topic]
        lines.append(f"| {topic} | **{cnt}** | {sev['CRITICAL']} | {sev['HIGH']} | {sev['MEDIUM']} |")
    lines.append("")
    
    # 四、信源画像
    lines.append("## 四、信源画像")
    lines.append("")
    lines.append(f"- 认证号: {verified_pseudo}/{len(pseudo)} ({verified_pseudo/len(pseudo)*100:.1f}%)")
    lines.append(f"- 非认证号: {len(pseudo)-verified_pseudo}/{len(pseudo)} ({(len(pseudo)-verified_pseudo)/len(pseudo)*100:.1f}%)")
    lines.append(f"- 高粉号(>10万粉): {high_fan_pseudo}/{len(pseudo)} ({high_fan_pseudo/len(pseudo)*100:.1f}%)")
    lines.append("")
    
    # 五、典型案例
    lines.append("## 五、典型案例")
    lines.append("")
    
    lines.append("### 🚨 高风险案例（Top 5 by risk_score）")
    lines.append("")
    for r in top_risk:
        sp = spread(r)
        harm = r["harm_line"] if r["harm_line"] != "none" else "—"
        verified = "✅" if r["verified"] else ""
        lines.append(f"- **[{r['severity']}] {verified} {r['username']}** ({r['followers_count']:,}粉)")
        lines.append(f"  > {r['text'][:100]}…")
        lines.append(f"  > risk={r['risk_score']:.1f} · 危害={harm} · 传播={sp}")
        lines.append("")
    
    lines.append("### 📊 高传播案例（Top 5 by 互动量）")
    lines.append("")
    for r in top_spread:
        sp = spread(r)
        harm = r["harm_line"] if r["harm_line"] != "none" else "—"
        verified = "✅" if r["verified"] else ""
        lines.append(f"- **{verified} {r['username']}** ({r['followers_count']:,}粉)")
        lines.append(f"  > {r['text'][:100]}…")
        lines.append(f"  > 转发{r['reposts_count']} · 评论{r['comments_count']} · 点赞{r['attitudes_count']} · 危害={harm}")
        lines.append("")
    
    # 六、下一步计划
    lines.append("## 六、下一步计划")
    lines.append("")
    lines.append("1. 单平台采集识别跑稳（当前：微博）")
    lines.append("2. GitHub Actions 每日自动化采集+分析")
    lines.append("3. 建立定期报告节奏（周报自动生成+推送）")
    lines.append("4. 多平台扩展（抖音/小红书/公众号）")
    lines.append("5. 危害链路完整度提升（欺诈证据链/风评攻击溯源）")
    lines.append("")
    
    report = "\n".join(lines)
    
    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(report)
        print(f"周报已生成: {output_path}")
    
    return report


if __name__ == "__main__":
    default_input = os.path.join(os.path.dirname(__file__), "data", "analysis_v3.1_2026-05-06_final.jsonl")
    default_output = os.path.join(os.path.dirname(__file__), "..", "reports", "weekly_report.md")
    
    input_path = sys.argv[1] if len(sys.argv) > 1 else default_input
    output_path = sys.argv[2] if len(sys.argv) > 2 else default_output
    
    report = weekly_report(input_path, output_path)
    print(report[:500] + "…" if len(report) > 500 else report)
