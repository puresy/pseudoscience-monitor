#!/usr/bin/env python3
"""
健康检查 - 伪科普监测系统

检查各组件状态：文件、API、Cookie、依赖。
"""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class CheckResult:
    """检查结果"""
    name: str
    status: str  # ok / warn / error
    message: str
    details: Optional[str] = None


def check_files(base_dir: str = ".") -> list[CheckResult]:
    """检查必要文件"""
    results = []
    base = Path(base_dir)

    required_files = [
        ("analyzer_v3.py", "分析引擎"),
        ("propagation_analyzer.py", "传播分析器"),
        ("report_agent.py", "报告生成器"),
        ("config.py", "配置管理"),
        ("cookie_manager.py", "Cookie管理器"),
        ("cost_tracker.py", "成本追踪器"),
        ("crawlers/base.py", "采集器基类"),
        ("data/rumor_knowledge_base.json", "知识库"),
    ]

    for path, desc in required_files:
        full = base / path
        if full.exists():
            size = full.stat().st_size
            results.append(CheckResult(desc, "ok", f"{path} ({size}B)"))
        else:
            results.append(CheckResult(desc, "error", f"缺失: {path}"))

    return results


def check_knowledge_base(base_dir: str = ".") -> CheckResult:
    """检查知识库完整性"""
    kb_path = Path(base_dir) / "data" / "rumor_knowledge_base.json"
    if not kb_path.exists():
        return CheckResult("知识库", "error", "文件不存在")
    try:
        with open(kb_path, "r", encoding="utf-8") as f:
            kb = json.load(f)
        if isinstance(kb, list):
            count = len(kb)
        elif isinstance(kb, dict):
            # 兼容 {articles: {url: {...}}} 格式
            articles = kb.get("articles", kb)
            count = len(articles) if isinstance(articles, (dict, list)) else 0
        else:
            count = 0
        return CheckResult("知识库", "ok", f"{count}条记录")
    except Exception as e:
        return CheckResult("知识库", "error", f"解析失败: {e}")


def check_api(api_key: str = "", api_url: str = "") -> CheckResult:
    """检查 LLM API 可用性"""
    if not api_key:
        return CheckResult("LLM API", "warn", "未配置 API Key")
    try:
        import requests
        resp = requests.post(
            api_url or "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "glm-4-flash",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 5,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return CheckResult("LLM API", "ok", "连接正常")
        else:
            return CheckResult("LLM API", "warn", f"HTTP {resp.status_code}")
    except ImportError:
        return CheckResult("LLM API", "warn", "requests 未安装")
    except Exception as e:
        return CheckResult("LLM API", "error", str(e)[:100])


def check_proxy() -> CheckResult:
    """检查代理状态"""
    proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    if not proxy:
        return CheckResult("代理", "warn", "未设置 HTTP_PROXY")
    try:
        import socket
        host, port = proxy.replace("http://", "").split(":")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((host, int(port)))
        sock.close()
        if result == 0:
            return CheckResult("代理", "ok", f"{proxy} 可达")
        else:
            return CheckResult("代理", "error", f"{proxy} 不可达")
    except Exception as e:
        return CheckResult("代理", "error", str(e)[:100])


def check_dependencies() -> list[CheckResult]:
    """检查 Python 依赖"""
    results = []
    deps = [
        ("requests", "HTTP 客户端"),
        ("json", "JSON 解析"),
    ]
    for module, desc in deps:
        try:
            __import__(module)
            results.append(CheckResult(desc, "ok", f"{module} 已安装"))
        except ImportError:
            results.append(CheckResult(desc, "error", f"{module} 未安装"))
    return results


def run_health_check(base_dir: str = ".", api_key: str = "") -> list[CheckResult]:
    """运行完整健康检查"""
    results = []
    results.extend(check_files(base_dir))
    results.append(check_knowledge_base(base_dir))
    results.extend(check_dependencies())
    results.append(check_api(api_key))
    results.append(check_proxy())
    return results


def format_report(results: list[CheckResult]) -> str:
    """格式化检查报告"""
    lines = [
        "# 系统健康检查",
        "",
        "| 状态 | 组件 | 说明 |",
        "|------|------|------|",
    ]
    for r in results:
        icon = {"ok": "✅", "warn": "⚠️", "error": "❌"}.get(r.status, "❓")
        lines.append(f"| {icon} | {r.name} | {r.message} |")

    ok = sum(1 for r in results if r.status == "ok")
    warn = sum(1 for r in results if r.status == "warn")
    err = sum(1 for r in results if r.status == "error")
    lines += [
        "",
        f"**结果**: {ok}项正常 / {warn}项警告 / {err}项异常",
    ]
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="系统健康检查")
    parser.add_argument("--dir", default=".", help="项目目录")
    parser.add_argument("--api-key", default="", help="LLM API Key")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    results = run_health_check(args.dir, args.api_key)

    if args.json:
        data = [{"name": r.name, "status": r.status, "message": r.message} for r in results]
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_report(results))


if __name__ == "__main__":
    main()
