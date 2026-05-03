#!/usr/bin/env python3
"""
辟谣平台抓取模块 - 伪科普监测系统 MVP

抓取 https://example.com/debunk/ 的辟谣文章，
构建本地谣言知识库供LLM核查参考。

用法：
    python piyao_crawler.py
    python piyao_crawler.py --output data/ --max-pages 10
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
from urllib.parse import urljoin

import requests
import yaml

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")


def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> dict:
    """加载配置文件"""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def fetch_with_retry(
    url: str,
    headers: Optional[dict] = None,
    timeout: int = 15,
    max_retries: int = 3,
    delay_range: tuple = (1, 3),
) -> Optional[requests.Response]:
    """
    带重试机制的HTTP GET请求。

    参数：
        url: 请求URL
        headers: 请求头
        timeout: 超时秒数
        max_retries: 最大重试次数
        delay_range: 重试延时范围（秒）

    返回：
        Response对象或None（失败时）
    """
    if headers is None:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    for retry in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            logger.warning(f"请求失败 (URL={url}, 重试={retry+1}/{max_retries}): {e}")
            if retry < max_retries - 1:
                time.sleep(random.uniform(*delay_range))
            else:
                logger.error(f"请求最终失败: {url}")
    return None


def fetch_rumor_list_api(base_url: str, config: Optional[dict] = None) -> list[dict]:
    """
    通过辟谣平台JSON API获取辟谣文章列表。
    API端点: /index/rumor
    返回文章基本信息列表。
    """
    piyao_config = (config or {}).get("crawler", {}).get("piyao", {})
    timeout = piyao_config.get("timeout", 15)
    max_retries = piyao_config.get("max_retries", 3)

    api_url = urljoin(base_url, "/index/rumor")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": base_url,
    }

    resp = fetch_with_retry(api_url, headers=headers, timeout=timeout, max_retries=max_retries)
    if resp is None:
        logger.warning("辟谣列表API请求失败")
        return []

    try:
        data = resp.json()
    except Exception as e:
        logger.error(f"辟谣列表API JSON解析失败: {e}")
        return []

    if data.get("code") != 0:
        logger.warning(f"辟谣列表API返回异常: code={data.get('code')}, msg={data.get('msg')}")
        return []

    articles = []
    for item in data.get("data", []):
        article_id = item.get("id", "")
        title = item.get("title", "")
        if not title:
            continue

        # 解析时间戳
        timestamp = item.get("create_time", "")
        date_str = ""
        if timestamp:
            try:
                dt = datetime.fromtimestamp(int(timestamp))
                date_str = dt.strftime("%Y-%m-%d")
            except (ValueError, OSError):
                pass

        detail_url = item.get("dump_url", "")
        if not detail_url and article_id:
            detail_url = urljoin(base_url, f"/rumor/rumordetail?id={article_id}")

        articles.append({
            "title": title,
            "url": detail_url,
            "date": date_str,
            "expert": item.get("expert_info", ""),
            "keywords": [k.get("keyword", "") for k in item.get("keywords", [])],
            "origin": item.get("origin", ""),
        })

    logger.info(f"API返回 {len(articles)} 篇辟谣文章")
    return articles


def fetch_rumor_list_html(base_url: str, field_types: list[int] = None, config: Optional[dict] = None) -> list[dict]:
    """
    从辟谣网站列表页HTML中解析文章链接和基本信息。
    页面: /rumor/rumorlist?type=N
    使用正则解析服务端渲染的文章列表。
    """
    if field_types is None:
        field_types = [0, 1, 2, 6, 8, 15, 16]

    piyao_config = (config or {}).get("crawler", {}).get("piyao", {})
    timeout = piyao_config.get("timeout", 15)
    max_retries = piyao_config.get("max_retries", 3)
    delay_min = piyao_config.get("delay_min", 1)
    delay_max = piyao_config.get("delay_max", 3)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    all_articles = []
    seen_ids = set()

    for field_type in field_types:
        url = urljoin(base_url, f"/rumor/rumorlist?type={field_type}")
        logger.info(f"抓取辟谣列表 type={field_type}: {url}")
        resp = fetch_with_retry(url, headers=headers, timeout=timeout, max_retries=max_retries)
        if resp is None:
            continue

        resp.encoding = resp.apparent_encoding or "utf-8"
        html = resp.text

        # 解析文章列表：提取 rumordetail?id=XXX 链接和标题
        detail_links = re.findall(
            r'href=["\']([^"\']*rumordetail\?id=([A-Za-z0-9]+))["\']',
            html,
        )
        titles = re.findall(
            r'rumor-list_item-title[^>]*>([^<]+)<',
            html,
        )

        for i, (link, article_id) in enumerate(detail_links):
            if article_id in seen_ids:
                continue
            seen_ids.add(article_id)

            title = titles[i].strip() if i < len(titles) else ""
            article_url = link if link.startswith("http") else urljoin(base_url, link)

            all_articles.append({
                "title": title,
                "url": article_url,
                "date": "",
            })

        logger.info(f"type={field_type} 解析到 {len(detail_links)} 篇文章")
        time.sleep(random.uniform(delay_min, delay_max))

    logger.info(f"HTML列表共获取 {len(all_articles)} 篇去重文章")
    return all_articles


def parse_article_list_html(html: str, base_url: str) -> list[dict]:
    """
    从辟谣网站列表页HTML中解析文章链接和基本信息。
    兼容旧接口 - 解析rumordetail链接和标题。
    """
    articles = []

    # 解析 rumordetail?id=XXX 类型链接
    detail_pattern = re.compile(
        r'<a[^>]+href=["\']([^"\']*rumordetail\?id=[A-Za-z0-9]+)["\'][^>]*>',
        re.DOTALL | re.IGNORECASE,
    )
    title_pattern = re.compile(
        r'rumor-list_item-title[^>]*>([^<]+)<',
        re.IGNORECASE,
    )

    links = detail_pattern.findall(html)
    titles = title_pattern.findall(html)

    for i, href in enumerate(links):
        article_url = urljoin(base_url, href.strip())
        title = titles[i].strip() if i < len(titles) else ""

        if not title or len(title) < 4:
            continue

        articles.append({
            "title": title,
            "url": article_url,
            "date": "",
        })

    # 去重（按URL）
    seen = set()
    unique = []
    for a in articles:
        if a["url"] not in seen:
            seen.add(a["url"])
            unique.append(a)

    return unique


def parse_article_detail_html(html: str) -> dict:
    """
    从辟谣文章详情页HTML中提取正文、分类、专家名等信息。
    适配 公开辟谣数据源/rumor/rumordetail 页面结构。
    """
    result = {
        "content": "",
        "category": "",
        "keywords": [],
        "expert": "",
    }

    # 提取正文 - 辟谣平台使用 class="rumor-content" 容器
    content_patterns = [
        re.compile(r'<div[^>]*class="[^"]*rumor[_-]?content[^"]*"[^>]*>(.*?)</div>\s*(?:<div|$)',
                    re.DOTALL | re.IGNORECASE),
        re.compile(r'<div[^>]*class="[^"]*article[_-]?content[^"]*"[^>]*>(.*?)</div>\s*(?:<div|</section|</main)',
                    re.DOTALL | re.IGNORECASE),
        re.compile(r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>\s*(?:<div[^>]*class="[^"]*(?:footer|sidebar|comment|aside))',
                    re.DOTALL | re.IGNORECASE),
        re.compile(r'<article[^>]*>(.*?)</article>', re.DOTALL | re.IGNORECASE),
    ]

    for pattern in content_patterns:
        match = pattern.search(html)
        if match:
            raw_content = match.group(1)
            # 清理HTML标签，保留段落结构
            text = re.sub(r"<br\s*/?>", "\n", raw_content)
            text = re.sub(r"</p>", "\n", text)
            text = re.sub(r"<[^>]+>", "", text)
            text = re.sub(r"\s*\n\s*", "\n", text).strip()
            if len(text) > 50:
                result["content"] = text
                break

    # 如果上面没匹配到，取所有<p>标签内容
    if not result["content"]:
        paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", html, re.DOTALL | re.IGNORECASE)
        texts = []
        for p in paragraphs:
            t = re.sub(r"<[^>]+>", "", p).strip()
            if len(t) > 10:
                texts.append(t)
        if texts:
            result["content"] = "\n".join(texts)

    # 提取标题（rumor-title）
    title_match = re.search(r'class="[^"]*rumor[_-]?title[^"]*"[^>]*>(.*?)</(?:div|h[1-6])>', html, re.DOTALL | re.IGNORECASE)
    if title_match:
        result["title_from_detail"] = re.sub(r"<[^>]+>", "", title_match.group(1)).strip()

    # 提取分类/标签
    meta_kw = re.search(r'<meta\s+name="[Kk]eywords"\s+content="([^"]*)"', html, re.IGNORECASE)
    if meta_kw:
        kws = [k.strip() for k in meta_kw.group(1).split(",") if k.strip()]
        result["keywords"] = kws

    # 提取专家名 - 辟谣页面格式：作者丨XXX / 审核丨XXX
    expert_patterns = [
        re.compile(r"作者[丨|｜：:]\s*([^\s<]{2,30})", re.IGNORECASE),
        re.compile(r"审核[丨|｜：:]\s*([^\s<]{2,30})", re.IGNORECASE),
        re.compile(r"(?:专家|来源)[：:]\s*([^\s<,，]{2,10})", re.IGNORECASE),
        re.compile(r'class="[^"]*(?:author|expert)[^"]*"[^>]*>(.*?)</(?:span|a|div)>', re.IGNORECASE),
    ]
    for pat in expert_patterns:
        match = pat.search(html)
        if match:
            expert = re.sub(r"<[^>]+>", "", match.group(1)).strip()
            if expert:
                result["expert"] = expert
                break

    return result


def crawl_piyao_list(base_url: str, max_pages: int = 5, config: Optional[dict] = None) -> list[dict]:
    """
    抓取辟谣平台文章列表。
    双通道采集：API + HTML列表页，合并去重。

    参数：
        base_url: 网站首页URL
        max_pages: 最多翻页数（控制HTML列表页的领域数量）
        config: 采集配置

    返回：
        文章基本信息列表
    """
    all_articles = []
    seen_urls = set()

    # 通道1: JSON API（/index/rumor）
    logger.info("=== 通道1: 辟谣列表API ===")
    api_articles = fetch_rumor_list_api(base_url, config=config)
    for article in api_articles:
        if article["url"] and article["url"] not in seen_urls:
            seen_urls.add(article["url"])
            all_articles.append(article)

    # 通道2: HTML列表页（/rumor/rumorlist?type=N）
    # 每个领域类型一页，max_pages控制访问的领域数
    field_types = [0, 1, 2, 6, 8, 15, 16][:max_pages]
    logger.info(f"=== 通道2: HTML列表页 (领域: {field_types}) ===")
    html_articles = fetch_rumor_list_html(base_url, field_types=field_types, config=config)
    for article in html_articles:
        if article["url"] and article["url"] not in seen_urls:
            seen_urls.add(article["url"])
            all_articles.append(article)

    logger.info(f"双通道共获取 {len(all_articles)} 篇去重文章链接")
    return all_articles


def crawl_article_detail(article: dict, config: Optional[dict] = None) -> dict:
    """
    抓取单篇文章详情，补充正文等信息。

    参数：
        article: 包含url和title的文章字典
        config: 采集配置

    返回：
        完整的文章信息字典
    """
    piyao_config = (config or {}).get("crawler", {}).get("piyao", {})
    timeout = piyao_config.get("timeout", 15)
    max_retries = piyao_config.get("max_retries", 3)

    result = {
        "title": article.get("title", ""),
        "url": article.get("url", ""),
        "date": article.get("date", ""),
        "content": "",
        "category": "",
        "keywords": [],
        "expert": "",
        "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    resp = fetch_with_retry(article["url"], timeout=timeout, max_retries=max_retries)
    if resp is None:
        logger.warning(f"文章详情抓取失败: {article['title']}")
        return result

    resp.encoding = resp.apparent_encoding or "utf-8"
    detail = parse_article_detail_html(resp.text)

    result.update({
        "content": detail.get("content", ""),
        "category": detail.get("category", ""),
        "keywords": detail.get("keywords", []),
        "expert": detail.get("expert", ""),
    })

    # 如果列表页没取到日期，尝试从详情页提取
    if not result["date"]:
        date_match = re.search(r"(\d{4})[年\-/](\d{1,2})[月\-/](\d{1,2})", resp.text)
        if date_match:
            result["date"] = f"{date_match.group(1)}-{date_match.group(2).zfill(2)}-{date_match.group(3).zfill(2)}"

    return result


def update_knowledge_base(articles: list[dict], kb_path: str) -> int:
    """
    将新抓取的辟谣文章合并到本地谣言知识库。
    知识库按URL去重，累积存储所有已知辟谣内容。

    参数：
        articles: 新抓取的文章列表
        kb_path: 知识库文件路径

    返回：
        新增条目数
    """
    # 加载现有知识库
    kb = {}
    if os.path.exists(kb_path):
        try:
            with open(kb_path, "r", encoding="utf-8") as f:
                kb_data = json.load(f)
                if isinstance(kb_data, dict):
                    kb = kb_data.get("articles", {})
                elif isinstance(kb_data, list):
                    # 兼容旧格式
                    kb = {a.get("url", ""): a for a in kb_data if a.get("url")}
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"知识库加载失败，将重新创建: {e}")

    # 合并新文章
    new_count = 0
    for article in articles:
        url = article.get("url", "")
        if url and url not in kb:
            # 构建知识库条目（精简版，用于LLM查询）
            kb[url] = {
                "title": article.get("title", ""),
                "content_summary": article.get("content", "")[:500],  # 截取摘要
                "date": article.get("date", ""),
                "category": article.get("category", ""),
                "keywords": article.get("keywords", []),
                "expert": article.get("expert", ""),
                "url": url,
            }
            new_count += 1

    # 写入知识库
    os.makedirs(os.path.dirname(kb_path) or ".", exist_ok=True)
    kb_output = {
        "version": "1.0",
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_articles": len(kb),
        "articles": kb,
    }
    with open(kb_path, "w", encoding="utf-8") as f:
        json.dump(kb_output, f, ensure_ascii=False, indent=2)

    logger.info(f"知识库更新完成: 新增 {new_count} 条，总计 {len(kb)} 条")
    return new_count


def run_piyao_crawler(
    output_dir: str,
    max_pages: int = 5,
    config_path: str = DEFAULT_CONFIG_PATH,
) -> tuple[str, str]:
    """
    运行辟谣平台抓取主流程。

    参数：
        output_dir: 输出目录
        max_pages: 最多翻页数
        config_path: 配置文件路径

    返回：
        (文章JSONL文件路径, 知识库文件路径) 的元组
    """
    config = load_config(config_path)
    piyao_config = config.get("crawler", {}).get("piyao", {})
    base_url = piyao_config.get("base_url", "https://example.com/debunk/")

    os.makedirs(output_dir, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    output_file = os.path.join(output_dir, f"piyao_articles_{date_str}.jsonl")
    kb_path = config.get("output", {}).get("knowledge_base", os.path.join(output_dir, "rumor_knowledge_base.json"))

    # 抓取文章列表
    article_list = crawl_piyao_list(base_url, max_pages=max_pages, config=config)

    # 抓取文章详情
    piyao_cfg = config.get("crawler", {}).get("piyao", {})
    delay_min = piyao_cfg.get("delay_min", 1)
    delay_max = piyao_cfg.get("delay_max", 3)

    full_articles = []
    for i, article in enumerate(article_list):
        logger.info(f"[{i+1}/{len(article_list)}] 抓取文章: {article['title']}")
        full_article = crawl_article_detail(article, config=config)
        full_articles.append(full_article)

        if i < len(article_list) - 1:
            time.sleep(random.uniform(delay_min, delay_max))

    # 输出JSONL
    with open(output_file, "w", encoding="utf-8") as f:
        for article in full_articles:
            f.write(json.dumps(article, ensure_ascii=False) + "\n")

    logger.info(f"文章输出完成: {output_file}，共 {len(full_articles)} 篇")

    # 更新知识库
    update_knowledge_base(full_articles, kb_path)

    return output_file, kb_path


def main():
    parser = argparse.ArgumentParser(
        description="辟谣平台抓取工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
    python piyao_crawler.py
    python piyao_crawler.py --output data/ --max-pages 10
        """,
    )
    parser.add_argument(
        "--output",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"),
        help="输出目录（默认: data/）",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=5,
        help="最多翻页数（默认: 5）",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help="配置文件路径（默认: config.yaml）",
    )

    args = parser.parse_args()

    output_file, kb_path = run_piyao_crawler(
        output_dir=args.output,
        max_pages=args.max_pages,
        config_path=args.config,
    )
    print(f"\n✅ 文章输出: {output_file}")
    print(f"✅ 知识库: {kb_path}")


if __name__ == "__main__":
    main()
