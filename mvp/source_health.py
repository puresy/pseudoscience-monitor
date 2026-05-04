#!/usr/bin/env python3
"""
源健康度追踪器 - 伪科普监测系统

功能：
1. 追踪每个种子词的信息密度（产出伪科普条数）
2. 试用期管理（新增种子词跑7天看产出）
3. 低产出降权/淘汰
4. 源健康报告
"""

import json
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


class SourceHealthTracker:
    """源健康度追踪器"""

    def __init__(self, health_file: str = "data/source_health.json", sources_file: str = "sources.json"):
        self.health_file = Path(health_file)
        self.sources_file = Path(sources_file)
        self.health_data = self._load_health()
        self.sources_config = self._load_sources()

    def _load_health(self) -> dict:
        if self.health_file.exists():
            with open(self.health_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"keywords": {}, "last_updated": ""}

    def _load_sources(self) -> dict:
        if self.sources_file.exists():
            with open(self.sources_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"keywords": {}, "health_rules": {}}

    def _save_health(self):
        self.health_file.parent.mkdir(parents=True, exist_ok=True)
        self.health_data["last_updated"] = datetime.now().isoformat()
        with open(self.health_file, "w", encoding="utf-8") as f:
            json.dump(self.health_data, f, ensure_ascii=False, indent=2)

    def record_run(self, keyword: str, results: list[dict]):
        """记录一次采集运行的结果"""
        if keyword not in self.health_data["keywords"]:
            self.health_data["keywords"][keyword] = {
                "first_seen": datetime.now().isoformat(),
                "status": "trial",
                "daily_runs": [],
                "total_crawled": 0,
                "total_pseudo": 0,
                "total_debunk": 0,
                "total_normal": 0,
                "total_nonsci": 0,
            }

        kw_data = self.health_data["keywords"][keyword]

        # 统计本次运行
        pseudo = sum(1 for r in results if r.get("content_type") == "PSEUDOSCIENCE")
        debunk = sum(1 for r in results if r.get("content_type") == "DEBUNKING")
        normal = sum(1 for r in results if r.get("content_type") == "NORMAL_SCIENCE")
        nonsci = sum(1 for r in results if r.get("content_type") == "NON_SCIENCE")

        today = datetime.now().strftime("%Y-%m-%d")
        kw_data["daily_runs"].append({
            "date": today,
            "crawled": len(results),
            "pseudo": pseudo,
            "debunk": debunk,
            "normal": normal,
            "nonsci": nonsci,
        })
        kw_data["total_crawled"] += len(results)
        kw_data["total_pseudo"] += pseudo
        kw_data["total_debunk"] += debunk
        kw_data["total_normal"] += normal
        kw_data["total_nonsci"] += nonsci

        # 保留最近30天
        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        kw_data["daily_runs"] = [r for r in kw_data["daily_runs"] if r["date"] >= cutoff]

        self._save_health()

    def check_trials(self) -> list[dict]:
        """检查试用期种子词，决定是否采纳"""
        rules = self.sources_config.get("health_rules", {})
        trial_days = rules.get("trial_days", 7)
        min_pseudo = rules.get("min_pseudo_for_adoption", 1)

        actions = []
        for kw, data in self.health_data.get("keywords", {}).items():
            if data.get("status") != "trial":
                continue

            first_seen = datetime.fromisoformat(data["first_seen"])
            days_active = (datetime.now() - first_seen).days

            if days_active >= trial_days:
                if data["total_pseudo"] >= min_pseudo:
                    data["status"] = "active"
                    actions.append({"keyword": kw, "action": "adopt", "reason": f"试用{days_active}天，产出{data['total_pseudo']}条伪科普"})
                else:
                    data["status"] = "demoted"
                    actions.append({"keyword": kw, "action": "demote", "reason": f"试用{days_active}天，仅产出{data['total_pseudo']}条伪科普"})

        if actions:
            self._save_health()
        return actions

    def check_demotions(self) -> list[dict]:
        """检查活跃种子词是否需要降权"""
        rules = self.sources_config.get("health_rules", {})
        demote_days = rules.get("demote_threshold_days", 7)
        demote_pseudo = rules.get("demote_threshold_pseudo", 0)
        disable_days = rules.get("auto_disable_threshold_days", 14)
        disable_pseudo = rules.get("auto_disable_threshold_pseudo", 0)

        actions = []
        cutoff_demote = (datetime.now() - timedelta(days=demote_days)).strftime("%Y-%m-%d")
        cutoff_disable = (datetime.now() - timedelta(days=disable_days)).strftime("%Y-%m-%d")

        for kw, data in self.health_data.get("keywords", {}).items():
            if data.get("status") != "active":
                continue

            # 最近N天的产出
            recent_pseudo = sum(
                r["pseudo"] for r in data.get("daily_runs", [])
                if r["date"] >= cutoff_demote
            )
            recent_total = sum(
                r["crawled"] for r in data.get("daily_runs", [])
                if r["date"] >= cutoff_demote
            )

            # 连续N天0产出 → 降权
            if recent_pseudo <= demote_pseudo and recent_total > 0:
                older_pseudo = sum(
                    r["pseudo"] for r in data.get("daily_runs", [])
                    if r["date"] >= cutoff_disable and r["date"] < cutoff_demote
                )
                if older_pseudo <= disable_pseudo:
                    data["status"] = "disabled"
                    actions.append({"keyword": kw, "action": "disable", "reason": f"连续{disable_days}天0伪科普产出"})
                else:
                    data["status"] = "demoted"
                    actions.append({"keyword": kw, "action": "demote", "reason": f"近{demote_days}天仅{recent_pseudo}条伪科普"})

        if actions:
            self._save_health()
        return actions

    def get_active_keywords(self) -> list[str]:
        """获取所有活跃（非淘汰）的种子词"""
        active = []
        for kw, data in self.health_data.get("keywords", {}).items():
            if data.get("status") in ("active", "trial"):
                active.append(kw)
        return active

    def get_report(self) -> dict:
        """生成源健康报告"""
        keywords = self.health_data.get("keywords", {})
        status_counts = defaultdict(int)
        for data in keywords.values():
            status_counts[data.get("status", "unknown")] += 1

        top_producers = sorted(
            [(kw, d["total_pseudo"]) for kw, d in keywords.items()],
            key=lambda x: -x[1]
        )[:10]

        zero_producers = [
            kw for kw, d in keywords.items()
            if d.get("status") == "active" and d["total_pseudo"] == 0
        ]

        return {
            "total_keywords": len(keywords),
            "status_distribution": dict(status_counts),
            "top_producers": top_producers,
            "zero_producers_count": len(zero_producers),
            "zero_producers": zero_producers[:10],
        }

    def format_report(self) -> str:
        """格式化健康报告"""
        r = self.get_report()
        lines = [
            "# 源健康度报告",
            "",
            f"**种子词总数**: {r['total_keywords']}",
            "",
            "## 状态分布",
            "",
            "| 状态 | 数量 |",
            "|------|------|",
        ]
        for status, count in r["status_distribution"].items():
            label = {"active": "活跃", "trial": "试用", "demoted": "降权", "disabled": "淘汰"}.get(status, status)
            lines.append(f"| {label} | {count} |")

        lines += [
            "",
            "## Top 产出种子词",
            "",
            "| 种子词 | 伪科普产出 |",
            "|--------|-----------|",
        ]
        for kw, count in r["top_producers"]:
            lines.append(f"| {kw} | {count}条 |")

        if r["zero_producers"]:
            lines += [
                "",
                f"## 零产出种子词（{r['zero_producers_count']}个）",
                "",
            ]
            for kw in r["zero_producers"]:
                lines.append(f"- {kw}")

        return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="源健康度管理")
    parser.add_argument("action", choices=["report", "check", "status"], help="操作")
    parser.add_argument("--health", default="data/source_health.json", help="健康数据文件")
    parser.add_argument("--sources", default="sources.json", help="源配置文件")
    args = parser.parse_args()

    tracker = SourceHealthTracker(args.health, args.sources)

    if args.action == "report":
        print(tracker.format_report())
    elif args.action == "check":
        trials = tracker.check_trials()
        demotions = tracker.check_demotions()
        print(f"试用期检查: {len(trials)}个")
        for t in trials:
            print(f"  {t['keyword']}: {t['action']} - {t['reason']}")
        print(f"降权检查: {len(demotions)}个")
        for d in demotions:
            print(f"  {d['keyword']}: {d['action']} - {d['reason']}")
    elif args.action == "status":
        active = tracker.get_active_keywords()
        print(f"活跃种子词: {len(active)}个")
        for kw in active:
            print(f"  {kw}")


if __name__ == "__main__":
    main()
