#!/usr/bin/env python3
"""
辟谣网站采集器 - 伪科普监测系统

从科学辟谣平台(piyao.kepuchina.cn)采集辟谣内容。
使用 Jina Reader 作为兜底方案（网站无RSS）。

用途：
1. 采集最新辟谣帖 → 补充知识库
2. 提取辟谣帖中的谣言主张 → 作为新的监测种子词（反向种子）
"""

import json
import re
import time
import logging
from pathlib import Path
from typing import Optional

from jina_reader import jina_fetch, extract_articles_from_markdown

logger = logging.getLogger(__name__)


def scrape_piyao_list(page: int = 1) -> list[dict]:
    """
    采集辟谣列表页。

    Returns:
        [{"title": ..., "url": ..., "summary": ...}, ...]
    """
    url = "https://piyao.kepuchina.cn/"
    md = jina_fetch(url)

    if not md:
        logger.warning(f"[piyao] 采集主页失败")
        return []

    # 从Markdown中提取辟谣详情链接
    import re
    articles = []
    seen_urls = set()

    # 匹配 [标题](链接) 格式
    matches = re.findall(r'\[([^\]]{5,80})\]\((https?://piyao\.kepuchina\.cn/rumor/rumordetail\?id=[^\)]+)\)', md)
    for title, url in matches:
        if url not in seen_urls and '流言' not in title:
            seen_urls.add(url)
            articles.append({"title": title.strip(), "url": url})

    logger.info(f"[piyao] 主页采集到 {len(articles)} 条辟谣详情")
    return articles


def scrape_piyao_detail(url: str) -> Optional[dict]:
    """
    采集单条辟谣详情。

    Returns:
        {"title": ..., "content": ..., "keywords": [...], "rumor_claim": ...}
    """
    md = jina_fetch(url)

    if not md:
        return None

    # 提取标题
    title_match = re.search(r'^#{1,3}\s+(.+)', md, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else ""

    # 提取正文（前2000字）
    lines = md.split('\n')
    content_lines = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#') and not line.startswith('![') and len(line) > 10:
            content_lines.append(line)
    content = ' '.join(content_lines)[:2000]

    # 提取关键词（从标题和正文中找常见谣言关键词）
    rumor_keywords = extract_rumor_keywords(title + " " + content)

    return {
        "title": title,
        "url": url,
        "content": content,
        "keywords": rumor_keywords,
        "source": "piyao",
    }


def extract_rumor_keywords(text: str) -> list[str]:
    """从辟谣文本中提取谣言关键词"""
    patterns = [
        r'(.{2,8})致癌',
        r'(.{2,8})有毒',
        r'(.{2,8})有害',
        r'不能(.{2,10})',
        r'(.{2,8})是假的',
        r'(.{2,8})是谣言',
        r'(.{2,8})不实',
        r'别再(.{2,10})了',
    ]

    keywords = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for m in matches:
            if len(m) >= 2 and len(m) <= 10:
                keywords.append(m.strip())

    return list(set(keywords))


def batch_scrape_piyao(pages: int = 3, delay: float = 3.0) -> list[dict]:
    """
    批量采集辟谣内容。

    Args:
        pages: 采集页数
        delay: 页间延时（秒）

    Returns:
        完整的辟谣条目列表
    """
    all_articles = []

    for page in range(1, pages + 1):
        articles = scrape_piyao_list(page)
        all_articles.extend(articles)

        if page < pages:
            time.sleep(delay)

    # 去重
    seen_urls = set()
    unique = []
    for a in all_articles:
        if a.get("url") and a["url"] not in seen_urls:
            seen_urls.add(a["url"])
            unique.append(a)

    logger.info(f"[piyao] 批量采集完成: {len(unique)} 条（去重后）")
    return unique


def extract_reverse_seeds(articles: list[dict]) -> list[str]:
    """
    从辟谣内容中提取反向种子词。

    辟谣帖里提到的谣言主张，可以作为新的监测目标。
    """
    seeds = set()
    for article in articles:
        title = article.get("title", "")
        content = article.get("content", "")

        # 从标题提取
        keywords = extract_rumor_keywords(title)
        seeds.update(keywords)

        # 从内容提取
        keywords = extract_rumor_keywords(content)
        seeds.update(keywords)

    return sorted(seeds)


def save_results(articles: list[dict], output_path: str):
    """保存采集结果"""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for article in articles:
            f.write(json.dumps(article, ensure_ascii=False) + "\n")
    logger.info(f"[piyao] 保存 {len(articles)} 条到 {output_path}")


def main():
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    parser = argparse.ArgumentParser(description="辟谣网站采集器")
    parser.add_argument("--pages", type=int, default=3, help="采集页数")
    parser.add_argument("--output", "-o", help="输出文件路径")
    parser.add_argument("--seeds", action="store_true", help="提取反向种子词")
    args = parser.parse_args()

    articles = batch_scrape_piyao(args.pages)
    print(f"采集到 {len(articles)} 条辟谣内容")

    if args.seeds:
        seeds = extract_reverse_seeds(articles)
        print(f"\n反向种子词 ({len(seeds)} 个):")
        for s in seeds:
            print(f"  {s}")

    if args.output:
        save_results(articles, args.output)
        print(f"已保存到 {args.output}")
    else:
        for a in articles[:5]:
            print(f"  {a.get('title', '')[:60]}")


if __name__ == "__main__":
    main()
