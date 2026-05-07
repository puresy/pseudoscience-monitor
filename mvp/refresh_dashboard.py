#!/usr/bin/env python3
"""
Dashboard 自动刷新脚本
读取最新 analysis jsonl，更新 dashboard.html 中的数值
用于 CI 每日自动刷新看板
"""

import json
import os
import re
import sys
from collections import Counter


def find_latest_analysis(data_dir: str, prefix: str = "analysis_v3.1_") -> str:
    """找最新分析文件（final优先）"""
    files = [f for f in os.listdir(data_dir) if f.startswith(prefix) and f.endswith(".jsonl")]
    if not files:
        # 回退到 analysis_YYYY-MM-DD.jsonl
        files = [f for f in os.listdir(data_dir) if f.startswith("analysis_") and not f.startswith("analysis_v") and f.endswith(".jsonl")]
    if not files:
        raise FileNotFoundError(f"在 {data_dir} 中找不到分析文件")
    # final 优先
    finals = [f for f in files if "final" in f.lower()]
    candidates = finals or files
    candidates.sort(reverse=True)
    return os.path.join(data_dir, candidates[0])


def compute_stats(filepath: str) -> dict:
    """从分析文件计算统计数据"""
    data = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line:
                data.append(json.loads(line))

    total = len(data)
    ct = Counter()
    severities = Counter()
    harm = Counter()
    llm_flipped = 0
    llm_called = 0

    for d in data:
        a = d.get("analysis", {})
        content_type = a.get("content_type", "UNKNOWN")
        severity = a.get("severity", "NONE")
        
        ct[content_type] += 1
        if content_type == "PSEUDOSCIENCE":
            severities[severity] += 1
        
        hl = a.get("harm_line", [])
        if isinstance(hl, list):
            for h in hl:
                harm[h] += 1
        elif isinstance(hl, str) and hl != "none":
            harm[hl] += 1
        
        if a.get("llm_flipped"):
            llm_flipped += 1
        if a.get("llm_analysis") and a.get("llm_analysis") != "":
            llm_called += 1

    pseudo = ct.get("PSEUDOSCIENCE", 0)
    debunk = ct.get("DEBUNKING", 0)
    normal = ct.get("NORMAL_SCIENCE", 0)
    nonsci = ct.get("NON_SCIENCE", 0)
    gray = ct.get("GRAY_ZONE", 0)

    return {
        "total": total,
        "pseudo": pseudo,
        "debunk": debunk,
        "normal": normal,
        "nonsci": nonsci,
        "gray": gray,
        "pseudo_pct": pseudo / total * 100 if total else 0,
        "debunk_pct": debunk / total * 100 if total else 0,
        "normal_pct": normal / total * 100 if total else 0,
        "nonsci_pct": nonsci / total * 100 if total else 0,
        "critical": severities.get("CRITICAL", 0),
        "high": severities.get("HIGH", 0),
        "medium": severities.get("MEDIUM", 0),
        "low": severities.get("LOW", 0),
        "fraud": harm.get("fraud", 0),
        "reputation_attack": harm.get("reputation_attack", 0),
        "cult": harm.get("cult", 0),
        "harm_total": sum(harm.values()),
        "llm_flipped": llm_flipped,
        "llm_called": llm_called,
    }


def get_donut_arcs(stats: dict) -> dict:
    """计算donut图的stroke-dasharray"""
    total = stats["total"]
    if total == 0:
        return {}
    return {
        "pseudo": f"{stats['pseudo']/total*100:.2f} {100-stats['pseudo']/total*100:.2f}",
        "debunk": f"{stats['debunk']/total*100:.2f} {100-stats['debunk']/total*100:.2f}",
        "normal": f"{stats['normal']/total*100:.2f} {100-stats['normal']/total*100:.2f}",
        "nonsci": f"{stats['nonsci']/total*100:.2f} {100-stats['nonsci']/total*100:.2f}",
    }


def refresh_dashboard(html_path: str, stats: dict, date_str: str = ""):
    """更新dashboard.html中的数值"""
    with open(html_path, "r") as f:
        html = f.read()

    s = stats
    d = date_str or ""

    # ============ KPI cards ============
    # 伪科普
    html = re.sub(
        r'(<div class="kpi-card pseudo">\s*<div class="kpi-number">)\d+(</div>\s*<div class="kpi-label">伪科普 PSEUDOSCIENCE</div>\s*<div class="kpi-sub">占比 )[\d.]+%( \(CRITICAL )\d+(\))',
        rf'\g<1>{s["pseudo"]}\g<2>{s["pseudo_pct"]:.1f}%\g<3>{s["critical"]}\g<4>',
        html,
    )
    # 辟谣
    html = re.sub(
        r'(<div class="kpi-card debunk-card">\s*<div class="kpi-number">)\d+(</div>\s*<div class="kpi-label">辟谣内容 DEBUNKING</div>\s*<div class="kpi-sub">占比 )[\d.]+%',
        rf'\g<1>{s["debunk"]}\g<2>{s["debunk_pct"]:.1f}%',
        html,
    )
    # 正常科普
    html = re.sub(
        r'(<div class="kpi-card normal-card">\s*<div class="kpi-number">)\d+(</div>\s*<div class="kpi-label">正常科普 NORMAL_SCIENCE</div>\s*<div class="kpi-sub">占比 )[\d.]+%',
        rf'\g<1>{s["normal"]}\g<2>{s["normal_pct"]:.1f}%',
        html,
    )

    # ============ CT cards ============
    for old_val, new_val in [
        (r'<div class="ct-num">\d+</div>\s*<div class="ct-label">伪科普/谣言</div>\s*<div class="ct-pct">[\d.]+%', 
         f'<div class="ct-num">{s["pseudo"]}</div>\n      <div class="ct-label">伪科普/谣言</div>\n      <div class="ct-pct">{s["pseudo_pct"]:.1f}%'),
        (r'<div class="ct-num">\d+</div>\s*<div class="ct-label">辟谣内容</div>\s*<div class="ct-pct">[\d.]+%',
         f'<div class="ct-num">{s["debunk"]}</div>\n      <div class="ct-label">辟谣内容</div>\n      <div class="ct-pct">{s["debunk_pct"]:.1f}%'),
        (r'<div class="ct-num">\d+</div>\s*<div class="ct-label">正常科普</div>\s*<div class="ct-pct">[\d.]+%',
         f'<div class="ct-num">{s["normal"]}</div>\n      <div class="ct-label">正常科普</div>\n      <div class="ct-pct">{s["normal_pct"]:.1f}%'),
        (r'<div class="ct-num">\d+</div>\s*<div class="ct-label">非科学内容</div>\s*<div class="ct-pct">[\d.]+%',
         f'<div class="ct-num">{s["nonsci"]}</div>\n      <div class="ct-label">非科学内容</div>\n      <div class="ct-pct">{s["nonsci_pct"]:.1f}%'),
    ]:
        html = re.sub(old_val, new_val, html, count=1)

    # ============ Improve badges ============
    for old_pat, new_str in [
        (r'<div class="num up">\d+</div><div class="desc">伪科普检出<br>[\d.]+%</div>',
         f'<div class="num up">{s["pseudo"]}</div><div class="desc">伪科普检出<br>{s["pseudo_pct"]:.1f}%</div>'),
        (r'<div class="num purple">\d+</div><div class="desc">危害主线检测<br>[^<]+</div>',
         f'<div class="num purple">{s["harm_total"]}</div><div class="desc">危害主线检测<br>欺诈{s["fraud"]}+风评{s["reputation_attack"]}+邪教{s["cult"]}</div>'),
        (r'<div class="num up">\d+</div><div class="desc">辟谣帖独立识别<br>占比 [\d.]+%</div>',
         f'<div class="num up">{s["debunk"]}</div><div class="desc">辟谣帖独立识别<br>占比 {s["debunk_pct"]:.1f}%</div>'),
    ]:
        html = re.sub(old_pat, new_str, html, count=1)

    # ============ Legends ============
    for old_pat, new_str in [
        (r'伪科普 PSEUDOSCIENCE</span><span class="legend-value"[^>]*>\d+ \([\d.]+%\)',
         f'伪科普 PSEUDOSCIENCE</span><span class="legend-value" style="color:var(--pseudo)">{s["pseudo"]} ({s["pseudo_pct"]:.1f}%)'),
        (r'辟谣 DEBUNKING</span><span class="legend-value"[^>]*>\d+ \([\d.]+%\)',
         f'辟谣 DEBUNKING</span><span class="legend-value" style="color:var(--debunk)">{s["debunk"]} ({s["debunk_pct"]:.1f}%)'),
        (r'正常科普 NORMAL_SCIENCE</span><span class="legend-value"[^>]*>\d+ \([\d.]+%\)',
         f'正常科普 NORMAL_SCIENCE</span><span class="legend-value" style="color:var(--normal-sci)">{s["normal"]} ({s["normal_pct"]:.1f}%)'),
        (r'非科学 NON_SCIENCE</span><span class="legend-value"[^>]*>\d+ \([\d.]+%\)',
         f'非科学 NON_SCIENCE</span><span class="legend-value" style="color:var(--nonsci)">{s["nonsci"]} ({s["nonsci_pct"]:.1f}%)'),
    ]:
        html = re.sub(old_pat, new_str, html, count=1)

    # ============ Donut arcs ============
    arcs = get_donut_arcs(stats)
    if arcs:
        arc_map = {
            r'stroke-dasharray="[\d.]+\s[\d.]+".*?(?=pseudo|伪科普)': ("pseudo", arcs["pseudo"]),
            r'stroke-dasharray="[\d.]+\s[\d.]+".*?(?=debunk|辟谣)': ("debunk", arcs["debunk"]),
            r'stroke-dasharray="[\d.]+\s[\d.]+".*?(?=normal|正常科普|NORMAL)': ("normal", arcs["normal"]),
            r'stroke-dasharray="[\d.]+\s[\d.]+".*?(?=nonsci|非科学|NON_SCI)': ("nonsci", arcs["nonsci"]),
        }
        for old_pat in arc_map:
            # 简化：直接替换四个arc值
            pass  # Donut需要精确上下文匹配，先用精确值
        # 用简单粗暴的方式替换
        for old_value, arc_name in [
            (r'(stroke-dasharray=")[\d.]+\s[\d.]+(")', "pseudo"),
        ]:
            pass  # 延迟到后续完善

    # ============ Severity bars ============
    sev_map = {
        "CRITICAL": (s["critical"], int(s["critical"]/max(s["pseudo"],1)*100)),
        "HIGH": (s["high"], int(s["high"]/max(s["pseudo"],1)*100)),
        "MEDIUM": (s["medium"], int(s["medium"]/max(s["pseudo"],1)*100)),
    }
    for label, (count, width) in sev_map.items():
        html = re.sub(
            rf'<span class="bar-label">{label}</span><div class="bar-track"><div class="bar-fill \w+" style="width:\d+%">\d+</div></div><span class="bar-value"[^>]*>\d+</span>',
            f'<span class="bar-label">{label}</span><div class="bar-track"><div class="bar-fill {"critical" if label=="CRITICAL" else "high" if label=="HIGH" else "medium"}" style="width:{width}%">{count}</div></div><span class="bar-value" style="color:var(--{"critical" if label=="CRITICAL" else "high" if label=="HIGH" else "medium"})">{count}</span>',
            html,
        )

    # ============ Section headers ============
    html = re.sub(r'共\d+条 \(小米', f'共{s["pseudo"]}条 (小米', html)

    # ============ Pipeline desc ============
    html = html.replace(
        f'DEBUNKING {s["debunk"]-1}', f'DEBUNKING {s["debunk"]}'
    ).replace(
        f'DEBUNKING {s["debunk"]+1}', f'DEBUNKING {s["debunk"]}'
    )
    # 更稳健的方式
    html = re.sub(r'DEBUNKING \d+', f'DEBUNKING {s["debunk"]}', html)
    html = re.sub(r'NORMAL \d+', f'NORMAL {s["normal"]}', html)
    html = re.sub(r'NON_SCI \d+', f'NON_SCI {s["nonsci"]}', html)
    html = re.sub(r'危害主线\d+条', f'危害主线{s["harm_total"]}条', html)

    # ============ Pipeline count ============
    html = re.sub(
        r'(<div class="pipe-count">)\d+(</div>\s*<div class="pipe-desc">PSEUDOSCIENCE)',
        rf'\g<1>{s["pseudo"]}\g<2>',
        html,
    )

    # ============ Footer ============
    html = re.sub(
        r'危害主线\d+条（[^)]+）',
        f'危害主线{s["harm_total"]}条（欺诈{s["fraud"]}+风评{s["reputation_attack"]}+邪教{s["cult"]}）',
        html,
    )
    html = re.sub(
        r'GRAY_ZONE \d+条',
        f'GRAY_ZONE {s["gray"]}条',
        html,
    )

    with open(html_path, "w") as f:
        f.write(html)

    return True


def main():
    mvp_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(mvp_dir, "data")
    dashboard_path = os.path.join(mvp_dir, "dashboard.html")
    date_str = sys.argv[1] if len(sys.argv) > 1 else ""

    # 找最新分析文件
    analysis_file = find_latest_analysis(data_dir)
    print(f"📂 分析文件: {analysis_file}")

    # 计算统计
    stats = compute_stats(analysis_file)
    print(f"📊 统计:")
    print(f"  总量: {stats['total']}")
    print(f"  伪科普: {stats['pseudo']} ({stats['pseudo_pct']:.1f}%)")
    print(f"  辟谣: {stats['debunk']} ({stats['debunk_pct']:.1f}%)")
    print(f"  正常科普: {stats['normal']} ({stats['normal_pct']:.1f}%)")
    print(f"  非科学: {stats['nonsci']} ({stats['nonsci_pct']:.1f}%)")
    print(f"  灰区: {stats['gray']}")
    print(f"  高危: {stats['critical']}, 高风险: {stats['high']}, 中风险: {stats['medium']}")
    print(f"  危害: {stats['harm_total']}条 (欺诈{stats['fraud']}+风评{stats['reputation_attack']}+邪教{stats['cult']})")
    print(f"  LLM调用: {stats['llm_called']}, 翻转: {stats['llm_flipped']}")

    # 刷新dashboard
    refresh_dashboard(dashboard_path, stats, date_str)
    print(f"✅ Dashboard 已刷新: {dashboard_path}")


if __name__ == "__main__":
    main()
