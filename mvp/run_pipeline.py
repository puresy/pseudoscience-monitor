#!/usr/bin/env python3
"""
伪科普监测系统 MVP - 整合管道

串联三个核心模块：采集 → 识别 → 输出

用法：
    python run_pipeline.py --source weibo --date 2026-04-23
    python run_pipeline.py --source piyao
    python run_pipeline.py --source all --date 2026-04-23
    python run_pipeline.py --source file --input data/weibo_raw_2026-04-23.jsonl
"""

import argparse
import json
import os
import sys
import logging
from datetime import datetime

import yaml

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# 项目根目录
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(PROJECT_DIR, "config.yaml")

# 导入各模块
sys.path.insert(0, PROJECT_DIR)
from weibo_crawler import run_weibo_crawler
from piyao_crawler import run_piyao_crawler
from analyzer import analyze_file, analyze_text, load_config


def run_weibo_pipeline(date_str: str, config_path: str, limit: int = 20) -> dict:
    """
    运行微博采集+分析管道。

    参数：
        date_str: 日期字符串（用于输出文件名）
        config_path: 配置文件路径
        limit: 每个关键词采集条数

    返回：
        {"crawl_file": str, "analysis_file": str, "crawl_count": int, "analysis_count": int}
    """
    config = load_config(config_path)
    data_dir = os.path.join(PROJECT_DIR, config.get("output", {}).get("data_dir", "data"))
    keywords_file = os.path.join(PROJECT_DIR, config.get("keywords", {}).get("file", "keywords.txt"))

    logger.info("=" * 60)
    logger.info("🔍 阶段1：微博采集")
    logger.info("=" * 60)

    crawl_file = run_weibo_crawler(
        keywords_file=keywords_file,
        output_dir=data_dir,
        limit_per_keyword=limit,
        config_path=config_path,
    )

    # 检查采集结果
    crawl_count = 0
    if os.path.exists(crawl_file):
        with open(crawl_file, "r", encoding="utf-8") as f:
            crawl_count = sum(1 for _ in f)
    logger.info(f"采集到 {crawl_count} 条微博")

    if crawl_count == 0:
        logger.warning("没有采集到数据，跳过分析阶段")
        return {
            "crawl_file": crawl_file,
            "analysis_file": "",
            "crawl_count": 0,
            "analysis_count": 0,
        }

    logger.info("=" * 60)
    logger.info("🧠 阶段2：LLM识别分析")
    logger.info("=" * 60)

    analysis_file = os.path.join(data_dir, f"analysis_{date_str}.jsonl")
    analysis_count = analyze_file(
        input_file=crawl_file,
        output_file=analysis_file,
        config_path=config_path,
        text_field="text",
    )

    return {
        "crawl_file": crawl_file,
        "analysis_file": analysis_file,
        "crawl_count": crawl_count,
        "analysis_count": analysis_count,
    }


def run_piyao_pipeline(config_path: str, max_pages: int = 5) -> dict:
    """
    运行辟谣网站抓取管道（更新知识库）。

    参数：
        config_path: 配置文件路径
        max_pages: 最大翻页数

    返回：
        {"article_file": str, "kb_file": str, "article_count": int}
    """
    config = load_config(config_path)
    data_dir = os.path.join(PROJECT_DIR, config.get("output", {}).get("data_dir", "data"))

    logger.info("=" * 60)
    logger.info("📚 辟谣网站抓取 & 知识库更新")
    logger.info("=" * 60)

    article_file, kb_file = run_piyao_crawler(
        output_dir=data_dir,
        max_pages=max_pages,
        config_path=config_path,
    )

    article_count = 0
    if os.path.exists(article_file):
        with open(article_file, "r", encoding="utf-8") as f:
            article_count = sum(1 for _ in f)

    return {
        "article_file": article_file,
        "kb_file": kb_file,
        "article_count": article_count,
    }


def run_file_pipeline(input_file: str, config_path: str, date_str: str) -> dict:
    """
    对已有的数据文件运行分析管道。

    参数：
        input_file: 输入JSONL文件
        config_path: 配置文件路径
        date_str: 日期字符串

    返回：
        {"analysis_file": str, "analysis_count": int}
    """
    config = load_config(config_path)
    data_dir = os.path.join(PROJECT_DIR, config.get("output", {}).get("data_dir", "data"))

    logger.info("=" * 60)
    logger.info("🧠 对已有数据运行分析")
    logger.info("=" * 60)

    analysis_file = os.path.join(data_dir, f"analysis_{date_str}.jsonl")
    analysis_count = analyze_file(
        input_file=input_file,
        output_file=analysis_file,
        config_path=config_path,
    )

    return {
        "analysis_file": analysis_file,
        "analysis_count": analysis_count,
    }


def print_summary(results: dict):
    """打印管道执行摘要"""
    print("\n" + "=" * 60)
    print("📊 执行摘要")
    print("=" * 60)

    for key, value in results.items():
        if key.endswith("_file") and value:
            print(f"  📁 {key}: {value}")
        elif key.endswith("_count"):
            print(f"  📈 {key}: {value}")

    # 如果有分析结果，打印风险分布统计
    analysis_file = results.get("analysis_file", "")
    if analysis_file and os.path.exists(analysis_file):
        severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "SKIP": 0}
        with open(analysis_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    severity = item.get("analysis", {}).get("severity", "SKIP")
                    severity_counts[severity] = severity_counts.get(severity, 0) + 1
                except json.JSONDecodeError:
                    pass

        print("\n  🚨 风险分布:")
        for level in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "SKIP"]:
            count = severity_counts.get(level, 0)
            if count > 0:
                bar = "█" * min(count, 50)
                emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢", "SKIP": "⚪"}.get(level, "")
                print(f"    {emoji} {level:10s}: {count:4d} {bar}")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="伪科普监测系统 MVP 整合管道",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
数据来源：
    weibo   - 微博采集 + 分析
    piyao   - 科学辟谣网站抓取（更新知识库）
    all     - 先更新知识库，再采集微博并分析
    file    - 对已有的数据文件运行分析

示例：
    python run_pipeline.py --source weibo --date 2026-04-23
    python run_pipeline.py --source piyao
    python run_pipeline.py --source all --date 2026-04-23
    python run_pipeline.py --source file --input data/weibo_raw_2026-04-23.jsonl
        """,
    )
    parser.add_argument(
        "--source",
        choices=["weibo", "piyao", "all", "file"],
        required=True,
        help="数据来源",
    )
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="日期（默认: 今天）",
    )
    parser.add_argument(
        "--input",
        help="输入文件路径（source=file时必填）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="每个关键词采集条数（默认: 20）",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=5,
        help="辟谣网站最大翻页数（默认: 5）",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help="配置文件路径（默认: config.yaml）",
    )

    args = parser.parse_args()

    # 验证参数
    if args.source == "file" and not args.input:
        parser.error("source=file 时必须指定 --input")

    start_time = datetime.now()
    logger.info(f"管道启动: source={args.source}, date={args.date}")

    results = {}

    try:
        if args.source == "piyao":
            results = run_piyao_pipeline(
                config_path=args.config,
                max_pages=args.max_pages,
            )

        elif args.source == "weibo":
            results = run_weibo_pipeline(
                date_str=args.date,
                config_path=args.config,
                limit=args.limit,
            )

        elif args.source == "all":
            # 先更新知识库
            piyao_results = run_piyao_pipeline(
                config_path=args.config,
                max_pages=args.max_pages,
            )
            # 再采集微博并分析
            weibo_results = run_weibo_pipeline(
                date_str=args.date,
                config_path=args.config,
                limit=args.limit,
            )
            results = {**piyao_results, **weibo_results}

        elif args.source == "file":
            results = run_file_pipeline(
                input_file=args.input,
                config_path=args.config,
                date_str=args.date,
            )

    except KeyboardInterrupt:
        logger.info("用户中断")
        sys.exit(1)
    except Exception as e:
        logger.error(f"管道执行失败: {e}", exc_info=True)
        sys.exit(1)

    elapsed = (datetime.now() - start_time).total_seconds()
    results["elapsed_seconds"] = round(elapsed, 1)

    print_summary(results)
    logger.info(f"管道执行完成，耗时 {elapsed:.1f}s")


if __name__ == "__main__":
    main()
