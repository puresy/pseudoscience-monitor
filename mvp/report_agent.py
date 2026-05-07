#!/usr/bin/env python3
"""伪科普监测 — 周报/日报自动生成，输出 Markdown 格式"""

import json
import os
import sys
from collections import Counter
from datetime import datetime


def find_latest_analysis(data_dir: str) -> str:
    files = sorted(os.listdir(data_dir))
    finals = [f for f in files if "v3.1" in f and "final" in f and f.endswith(".jsonl")]
    if finals:
        return os.path.join(data_dir, finals[-1])
    v31 = [f for f in files if "v3.1" in f and f.endswith(".jsonl")]
    if v31:
        return os.path.join(data_dir, v31[-1])
    others = sorted([f for f in files if f.startswith("analysis_") and f.endswith(".jsonl")], reverse=True)
    if others:
        return os.path.join(data_dir, others[0])
    raise FileNotFoundError(f"No analysis file in {data_dir}")


TOPIC_KEYWORDS = [
    "黄曲霉","致癌","排毒","肝经","经络","气血","拍八虚","倪师",
    "量子","酸碱","疫苗","转基因","辐射","添加剂","防腐剂",
    "辟谷","断食","酵素","磁疗","远红外","负离子",
    "中医","脉轮","能量","灵修","冥想","水知道",
    "微波炉","味精","鸡精","阿斯巴甜","代糖",
    "干细胞","基因编辑","克隆","纳米",
]

HARM_CN = {"fraud":"欺诈","reputation_attack":"风评攻击","cult":"邪教属性","none":"无"}


def extract_topic(text):
    for kw in TOPIC_KEYWORDS:
        if kw in text:
            return kw
    return "其他"


def compute_report(data, date_str=""):
    total = len(data)
    ct, severities, harm, topics = Counter(), Counter(), Counter(), Counter()
    verified = high_followers = llm_flipped = llm_called = 0
    top_cases = []
    # 交叉分析
    topic_harm = {}         # topic -> Counter(harm)
    topic_verified = {}     # topic -> (verified_count, total_count)
    topic_severity = {}     # topic -> Counter(severity)
    harm_examples = {}      # harm -> [(text, topic, verified)]

    for d in data:
        a = d.get("analysis", {})
        ct_val = a.get("content_type", "UNKNOWN")
        sev = a.get("severity", "NONE")
        ct[ct_val] += 1

        if ct_val == "PSEUDOSCIENCE":
            severities[sev] += 1
            topic = extract_topic(d.get("text", ""))
            topics[topic] += 1
            if d.get("verified"):
                verified += 1
            if d.get("followers_count", 0) > 100000:
                high_followers += 1

            # 话题×危害交叉
            hl = a.get("harm_line", [])
            if topic not in topic_harm:
                topic_harm[topic] = Counter()
            if topic not in topic_verified:
                topic_verified[topic] = [0, 0]
            if topic not in topic_severity:
                topic_severity[topic] = Counter()
            topic_verified[topic][1] += 1
            topic_severity[topic][sev] += 1
            if d.get("verified"):
                topic_verified[topic][0] += 1
            if isinstance(hl, list):
                for h in hl:
                    topic_harm[topic][h] += 1
            elif isinstance(hl, str) and hl not in ("none", ""):
                topic_harm[topic][hl] += 1

            if sev in ("CRITICAL", "HIGH"):
                top_cases.append({
                    "username": d.get("username",""), "verified": d.get("verified", False),
                    "followers": d.get("followers_count", 0), "text": d.get("text","")[:120],
                    "severity": sev, "topic": topic, "harm_line": a.get("harm_line", []),
                })
        # 全局危害统计（在PSEUDOSCIENCE块内hl已定义，这里复用）
        hl = a.get("harm_line", [])
        if hl:
            if isinstance(hl, list):
                for h in hl:
                    harm[h] += 1
                    if h not in harm_examples:
                        harm_examples[h] = []
                    if len(harm_examples[h]) < 5 and ct_val == "PSEUDOSCIENCE":
                        harm_examples[h].append((d.get("text","")[:80], extract_topic(d.get("text","")), d.get("verified",False)))
            elif isinstance(hl, str) and hl not in ("none", ""):
                harm[hl] += 1
                if hl not in harm_examples:
                    harm_examples[hl] = []
                if len(harm_examples[hl]) < 5 and ct_val == "PSEUDOSCIENCE":
                    harm_examples[hl].append((d.get("text","")[:80], extract_topic(d.get("text","")), d.get("verified",False)))

        if a.get("llm_flipped"): llm_flipped += 1
        if a.get("llm_analysis") and a.get("llm_analysis") != "": llm_called += 1

    pseudo = ct.get("PSEUDOSCIENCE", 0)
    top_cases.sort(key=lambda x: (0 if x["severity"]=="CRITICAL" else 1, -x["followers"]))
    top_cases = top_cases[:10]

    return {
        "date": date_str or datetime.now().strftime("%Y-%m-%d"), "total": total,
        "pseudo": pseudo, "debunk": ct.get("DEBUNKING", 0),
        "normal": ct.get("NORMAL_SCIENCE", 0), "nonsci": ct.get("NON_SCIENCE", 0),
        "gray": ct.get("GRAY_ZONE", 0),
        "critical": severities.get("CRITICAL", 0), "high": severities.get("HIGH", 0),
        "medium": severities.get("MEDIUM", 0),
        "fraud": harm.get("fraud", 0), "reputation_attack": harm.get("reputation_attack", 0),
        "cult": harm.get("cult", 0), "harm_total": sum(harm.values()),
        "verified_pct": verified / pseudo * 100 if pseudo else 0,
        "high_followers_pct": high_followers / pseudo * 100 if pseudo else 0,
        "llm_flipped": llm_flipped, "llm_called": llm_called,
        "topics": topics.most_common(10), "top_cases": top_cases,
        # 分析字段
        "topic_harm": topic_harm, "topic_verified": topic_verified,
        "topic_severity": topic_severity, "harm_examples": harm_examples,
    }


def build_markdown(r):
    lines = [
        f"# 伪科普监测周报 — {r['date']}",
        "",
        f"> 采集 {r['total']} 条 · LLM {r['llm_called']} 次 · 翻转 {r['llm_flipped']} 次",
        "",
        "## 一、分类概览", "",
        "| 分类 | 数量 | 占比 |",
        "|------|------|------|",
        f"| 🔴 伪科普 | {r['pseudo']} | {r['pseudo']/r['total']*100:.1f}% |",
        f"| 🟢 辟谣 | {r['debunk']} | {r['debunk']/r['total']*100:.1f}% |",
        f"| 🔵 正常科普 | {r['normal']} | {r['normal']/r['total']*100:.1f}% |",
        f"| ⚪ 非科学 | {r['nonsci']} | {r['nonsci']/r['total']*100:.1f}% |",
    ]
    if r["gray"]:
        lines.append(f"| ⚠️ 灰色地带 | {r['gray']} | — |")
    lines += [
        "",
        "## 二、伪科普严重度", "",
        f"- **严重 (CRITICAL)**: {r['critical']} 条",
        f"- **高风险 (HIGH)**: {r['high']} 条",
        f"- **中风险 (MEDIUM)**: {r['medium']} 条", "",
        "## 三、危害主线", "",
        f"- **欺诈**: {r['fraud']} 条",
        f"- **风评攻击**: {r['reputation_attack']} 条",
        f"- **邪教属性**: {r['cult']} 条", "",
        "## 四、谣言话题热度", "",
        "| 话题 | 提及次数 |",
        "|------|----------|",
    ]
    for topic, count in r["topics"]:
        lines.append(f"| {topic} | {count} |")
    lines += ["", "## 五、重点案例", ""]
    for i, case in enumerate(r["top_cases"], 1):
        badge = "🔴" if case["severity"] == "CRITICAL" else "🟠"
        vbadge = "✅认证" if case["verified"] else "普通"
        fans = f"{case['followers']/10000:.0f}万粉" if case["followers"] > 10000 else f"{case['followers']}粉"
        raw = case["harm_line"]
        if isinstance(raw, list):
            harm_tags = "、".join(HARM_CN.get(h, h) for h in raw[:3]) or "无"
        elif isinstance(raw, str) and raw not in ("none", "", None):
            harm_tags = HARM_CN.get(raw, raw)
        else:
            harm_tags = "无"
        lines += [
            f"### {badge} 案例 {i} · {vbadge} · {fans}",
            f"**话题**: {case['topic']} | **危害**: {harm_tags}",
            f"> {case['text']}", "",
        ]
    lines += [
        "## 六、传播者画像", "",
        f"- 认证号参与比例: {r['verified_pct']:.1f}%",
        f"- 粉丝 > 10万的高影响账号: {r['high_followers_pct']:.1f}%",
        f"- 认证号 ≠ 可信 — 认证标签增加了伪科普的传播半径和误导性", "",
    ]

    # 七、话题×危害交叉分析
    lines += ["## 七、话题×危害交叉分析", ""]
    th_sorted = sorted(r["topic_harm"].items(), key=lambda x: -sum(x[1].values()))[:8]
    for topic, harm_ct in th_sorted:
        harms_str = " ".join(f"{HARM_CN.get(h,h)}×{c}" for h, c in harm_ct.most_common(5))
        v = r["topic_verified"].get(topic, [0,1])
        vpct = v[0]/v[1]*100 if v[1] else 0
        lines.append(f"- **{topic}** ({v[1]}条, 认证率{vpct:.0f}%): {harms_str}")
    lines.append("")

    # 八、危害主线分析
    lines += ["## 八、危害主线分析", ""]
    for h_key, h_cn in [("fraud","欺诈"), ("reputation_attack","风评攻击"), ("cult","邪教属性")]:
        if r.get(h_key, 0):
            examples = r["harm_examples"].get(h_key, [])
            lines.append(f"### {h_cn} ({r[h_key]}条)")
            for txt, topic, verif in examples[:3]:
                vtag = "认证|" if verif else ""
                lines.append(f"- [{topic}] {vtag}{txt}")
            lines.append("")

    lines += [
        "---",
        f"*报告由伪科普监测系统 v3.1 自动生成 · {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
    ]
    return "\n".join(lines)


def main():
    mvp_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(mvp_dir, "data")
    analysis_file = find_latest_analysis(data_dir)
    print(f"📂 数据: {analysis_file}")
    data = [json.loads(line) for line in open(analysis_file) if line.strip()]
    date_str = sys.argv[1] if len(sys.argv) > 1 else ""
    r = compute_report(data, date_str)
    report = build_markdown(r)
    out = os.path.join(data_dir, f"weekly_report_{r['date']}.md")
    with open(out, "w") as f: f.write(report)
    print(report)
    print(f"\n✅ 报告已保存: {out}")


if __name__ == "__main__":
    main()
