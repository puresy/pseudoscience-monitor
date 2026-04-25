#!/usr/bin/env python3
"""
微博采集模块 - 伪科普监测系统 MVP

通过微博移动端公开搜索API按关键词采集疑似伪科普内容。
不需要登录态，使用移动端公开接口。

用法：
    python weibo_crawler.py --keywords keywords.txt --output data/ --limit 20
"""

import argparse
import json
import os
import random
import re
import sys
import time
import logging
from datetime import datetime
from typing import Optional

import requests
import yaml

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")


def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> dict:
    """加载配置文件"""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_keywords(keywords_file: str) -> list[str]:
    """
    从关键词文件加载关键词列表。
    每行一个关键词/关键词组合，#开头为注释，空行忽略。
    """
    keywords = []
    with open(keywords_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                keywords.append(line)
    logger.info(f"加载了 {len(keywords)} 个关键词")
    return keywords


def parse_weibo_time(time_str: str) -> str:
    """
    解析微博时间字符串，统一转换为 ISO 格式。
    微博返回的时间格式多样：刚刚、X分钟前、X小时前、昨天 HH:MM、MM-DD、yyyy-MM-DD 等
    """
    if not time_str:
        return ""
    now = datetime.now()
    try:
        if "刚刚" in time_str:
            return now.strftime("%Y-%m-%d %H:%M:%S")
        elif "分钟前" in time_str:
            minutes = int(re.search(r"(\d+)", time_str).group(1))
            from datetime import timedelta
            dt = now - timedelta(minutes=minutes)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        elif "小时前" in time_str:
            hours = int(re.search(r"(\d+)", time_str).group(1))
            from datetime import timedelta
            dt = now - timedelta(hours=hours)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        elif "昨天" in time_str:
            from datetime import timedelta
            yesterday = now - timedelta(days=1)
            time_part = time_str.replace("昨天 ", "").strip()
            return f"{yesterday.strftime('%Y-%m-%d')} {time_part}:00"
        elif re.match(r"\d{4}-\d{2}-\d{2}", time_str):
            return time_str
        elif re.match(r"\d{2}-\d{2}", time_str):
            return f"{now.year}-{time_str} 00:00:00"
        else:
            return time_str
    except Exception:
        return time_str


def clean_html(text: str) -> str:
    """清理HTML标签，保留纯文本"""
    if not text:
        return ""
    # 移除HTML标签
    text = re.sub(r"<[^>]+>", "", text)
    # 解码HTML实体
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    text = text.replace("&nbsp;", " ")
    # 清理多余空白
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_weibo_item(card: dict) -> Optional[dict]:
    """
    从微博API返回的单条card中提取结构化数据。
    返回None表示此条不是有效微博。
    """
    mblog = card.get("mblog")
    if not mblog:
        return None

    user = mblog.get("user", {})
    if not user:
        return None

    # 提取正文（优先使用长文本）
    text = mblog.get("longText", {}).get("longTextContent", "") if mblog.get("isLongText") else ""
    if not text:
        text = mblog.get("text", "")
    text = clean_html(text)

    if not text:
        return None

    # 构造来源链接
    mid = mblog.get("mid", mblog.get("id", ""))
    uid = user.get("id", "")
    source_url = f"https://m.weibo.cn/detail/{mid}" if mid else ""

    return {
        "weibo_id": str(mid),
        "username": user.get("screen_name", ""),
        "user_id": str(uid),
        "followers_count": user.get("followers_count", 0),
        "publish_time": parse_weibo_time(mblog.get("created_at", "")),
        "text": text,
        "reposts_count": mblog.get("reposts_count", 0),
        "comments_count": mblog.get("comments_count", 0),
        "attitudes_count": mblog.get("attitudes_count", 0),
        "source_url": source_url,
        "keyword": "",  # 由调用方填充
        "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def search_weibo(keyword: str, config: dict, limit: int = 20) -> list[dict]:
    """
    通过微博移动端搜索API搜索关键词，返回结构化结果列表。

    参数：
        keyword: 搜索关键词
        config: 采集配置（包含headers、timeout等）
        limit: 最多返回条数
    """
    weibo_config = config.get("crawler", {}).get("weibo", {})
    base_url = weibo_config.get("base_url", "https://m.weibo.cn/api/container/getIndex")
    headers = weibo_config.get("headers", {})
    timeout = weibo_config.get("timeout", 15)
    max_retries = weibo_config.get("max_retries", 3)

    results = []
    page = 1
    seen_ids = set()

    while len(results) < limit:
        params = {
            "containerid": f"100103type=1&q={keyword}",
            "page_type": "searchall",
            "page": page,
        }

        # 带重试的请求
        resp = None
        for retry in range(max_retries):
            try:
                resp = requests.get(
                    base_url,
                    params=params,
                    headers=headers,
                    timeout=timeout,
                )
                resp.raise_for_status()
                break
            except requests.RequestException as e:
                logger.warning(f"请求失败 (关键词={keyword}, 页={page}, 重试={retry+1}/{max_retries}): {e}")
                if retry < max_retries - 1:
                    time.sleep(random.uniform(2, 5))
                else:
                    logger.error(f"请求最终失败: 关键词={keyword}, 页={page}")
                    return results

        if resp is None:
            break

        try:
            data = resp.json()
        except json.JSONDecodeError:
            logger.error(f"JSON解析失败: 关键词={keyword}, 页={page}")
            break

        # 检查返回状态
        if data.get("ok") != 1:
            logger.warning(f"API返回异常: 关键词={keyword}, 页={page}, data.ok={data.get('ok')}")
            break

        cards = data.get("data", {}).get("cards", [])
        if not cards:
            logger.info(f"没有更多结果: 关键词={keyword}, 页={page}")
            break

        # 本页是否有新数据
        new_count = 0
        for card in cards:
            # card_type=9 是普通微博
            if card.get("card_type") != 9:
                # card_group中也可能包含微博（搜索结果有时嵌套）
                card_group = card.get("card_group", [])
                for sub_card in card_group:
                    if sub_card.get("card_type") == 9:
                        item = extract_weibo_item(sub_card)
                        if item and item["weibo_id"] not in seen_ids:
                            item["keyword"] = keyword
                            seen_ids.add(item["weibo_id"])
                            results.append(item)
                            new_count += 1
                            if len(results) >= limit:
                                break
                continue

            item = extract_weibo_item(card)
            if item and item["weibo_id"] not in seen_ids:
                item["keyword"] = keyword
                seen_ids.add(item["weibo_id"])
                results.append(item)
                new_count += 1
                if len(results) >= limit:
                    break

        if new_count == 0:
            logger.info(f"本页无新数据，停止翻页: 关键词={keyword}, 页={page}")
            break

        page += 1
        # 随机延时
        delay = random.uniform(
            weibo_config.get("delay_min", 2),
            weibo_config.get("delay_max", 5),
        )
        logger.debug(f"翻页延时 {delay:.1f}s")
        time.sleep(delay)

    logger.info(f"关键词 [{keyword}] 采集到 {len(results)} 条微博")
    return results


def run_weibo_crawler(
    keywords_file: str,
    output_dir: str,
    limit_per_keyword: int = 20,
    config_path: str = DEFAULT_CONFIG_PATH,
) -> str:
    """
    运行微博采集主流程。

    参数：
        keywords_file: 关键词文件路径
        output_dir: 输出目录
        limit_per_keyword: 每个关键词最多采集条数
        config_path: 配置文件路径

    返回：
        输出文件路径
    """
    config = load_config(config_path)
    keywords = load_keywords(keywords_file)

    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)

    # 输出文件
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_file = os.path.join(output_dir, f"weibo_raw_{date_str}.jsonl")

    total_count = 0
    weibo_config = config.get("crawler", {}).get("weibo", {})

    with open(output_file, "a", encoding="utf-8") as f:
        for i, keyword in enumerate(keywords):
            logger.info(f"[{i+1}/{len(keywords)}] 搜索关键词: {keyword}")

            items = search_weibo(keyword, config, limit=limit_per_keyword)

            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
                total_count += 1

            # 关键词之间的延时
            if i < len(keywords) - 1:
                delay = random.uniform(
                    weibo_config.get("delay_min", 2),
                    weibo_config.get("delay_max", 5),
                )
                logger.info(f"关键词间延时 {delay:.1f}s")
                time.sleep(delay)

    logger.info(f"采集完成，共 {total_count} 条微博，输出到: {output_file}")
    return output_file


def main():
    parser = argparse.ArgumentParser(
        description="微博伪科普内容采集工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
    python weibo_crawler.py
    python weibo_crawler.py --keywords keywords.txt --output data/ --limit 10
        """,
    )
    parser.add_argument(
        "--keywords",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "keywords.txt"),
        help="关键词文件路径（默认: keywords.txt）",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"),
        help="输出目录（默认: data/）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="每个关键词最多采集条数（默认: 20）",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help="配置文件路径（默认: config.yaml）",
    )

    args = parser.parse_args()

    output_file = run_weibo_crawler(
        keywords_file=args.keywords,
        output_dir=args.output,
        limit_per_keyword=args.limit,
        config_path=args.config,
    )
    print(f"\n✅ 输出文件: {output_file}")


if __name__ == "__main__":
    main()
