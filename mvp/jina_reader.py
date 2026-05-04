#!/usr/bin/env python3
"""
Jina Reader 兜底采集器 - 伪科普监测系统

当常规爬虫解析失败时，用 r.jina.ai 将页面转为 Markdown。
适用于：微博长文、动态渲染页面、反爬严重的站点。

用法：
    from jina_reader import jina_fetch
    md = jina_fetch("https://example.com/article")
"""

import re
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

JINA_BASE = "https://r.jina.ai"
DEFAULT_TIMEOUT = 30
RATE_LIMIT_DELAY = 2  # 秒


def jina_fetch(url: str, timeout: int = DEFAULT_TIMEOUT, return_format: str = "markdown") -> Optional[str]:
    """
    通过 Jina Reader 获取页面内容。

    Args:
        url: 目标URL
        timeout: 超时秒数
        return_format: "markdown" 或 "text"

    Returns:
        页面内容（Markdown/文本），失败返回 None
    """
    import requests

    jina_url = f"{JINA_BASE}/{url}"
    headers = {
        "Accept": "application/json",
        "X-Return-Format": return_format,
    }

    try:
        resp = requests.get(jina_url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            content = data.get("data", {}).get("content", "")
            if content:
                logger.info(f"[jina] 成功获取 {url} ({len(content)} 字符)")
                return content
            else:
                logger.warning(f"[jina] {url} 返回空内容")
                return None
        else:
            logger.warning(f"[jina] {url} HTTP {resp.status_code}")
            return None
    except requests.exceptions.Timeout:
        logger.warning(f"[jina] {url} 超时")
        return None
    except Exception as e:
        logger.error(f"[jina] {url} 异常: {e}")
        return None


def jina_fetch_text(url: str) -> Optional[str]:
    """获取纯文本版本"""
    return jina_fetch(url, return_format="text")


def extract_articles_from_markdown(md: str) -> list[dict]:
    """
    从 Jina Reader 返回的 Markdown 中提取文章信息。

    适用于微博搜索结果页、列表页等。
    """
    articles = []

    # 尝试按标题分割
    sections = re.split(r'\n(?=#{1,3}\s)', md)

    for section in sections:
        if not section.strip():
            continue

        # 提取标题
        title_match = re.match(r'^#{1,3}\s+(.+)', section)
        title = title_match.group(1).strip() if title_match else ""

        # 提取链接
        links = re.findall(r'\[.*?\]\((https?://[^\)]+)\)', section)
        url = links[0] if links else ""

        # 提取正文（去掉标题行和空行）
        body_lines = []
        for line in section.split('\n'):
            line = line.strip()
            if line and not line.startswith('#') and not line.startswith('![') and len(line) > 5:
                body_lines.append(line)
        body = ' '.join(body_lines)[:500]

        if title and len(title) > 3:
            articles.append({
                "title": title,
                "url": url,
                "text": body,
                "source": "jina_reader",
            })

    return articles


def jina_search_weibo(keyword: str) -> list[dict]:
    """
    用 Jina Reader 获取微博搜索结果。

    作为 weibo_crawler.py 的 fallback。
    """
    import requests
    from urllib.parse import quote

    search_url = f"https://s.weibo.com/weibo?q={quote(keyword)}"
    md = jina_fetch(search_url)

    if not md:
        return []

    return extract_articles_from_markdown(md)


def batch_jina_fetch(urls: list[str], delay: float = RATE_LIMIT_DELAY) -> dict[str, Optional[str]]:
    """
    批量获取多个URL。

    Args:
        urls: URL列表
        delay: 请求间隔（秒）

    Returns:
        {url: content} 字典
    """
    results = {}
    for i, url in enumerate(urls):
        results[url] = jina_fetch(url)
        if i < len(urls) - 1:
            time.sleep(delay)
    return results


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python jina_reader.py <url>")
        print("示例: python jina_reader.py https://weibo.com/1234567890")
        sys.exit(1)

    url = sys.argv[1]
    content = jina_fetch(url)

    if content:
        print(f"获取成功 ({len(content)} 字符)")
        print("---")
        print(content[:2000])
    else:
        print("获取失败")
