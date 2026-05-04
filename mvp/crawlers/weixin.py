#!/usr/bin/env python3
"""
公众号采集器 - 伪科普监测系统

通过搜狗微信搜索间接采集公众号文章。
注意：搜狗微信搜索有较严格的反爬限制，需要控制频率。
"""

import json
import logging
import re
from typing import Optional
from urllib.parse import quote

from .base import BaseCrawler, CrawlResult

logger = logging.getLogger(__name__)


class WeixinCrawler(BaseCrawler):
    """公众号文章采集器（通过搜狗微信搜索）"""

    SEARCH_API = "https://weixin.sogou.com/weixin"

    @property
    def platform_name(self) -> str:
        return "weixin"

    def search(self, keyword: str, limit: int = 20) -> list[CrawlResult]:
        results = []
        page = 1

        while len(results) < limit:
            params = {
                "type": 2,  # 2=搜文章, 1=搜公众号
                "query": keyword,
                "page": page,
                "ie": "utf8",
            }

            headers = {
                "Referer": "https://weixin.sogou.com/",
                "Cookie": "SUID=test",  # 基础 cookie
            }

            resp = self._retry_request(self.SEARCH_API, params=params, headers=headers)
            if not resp:
                logger.warning(f"[weixin] 搜索 '{keyword}' 第{page}页失败")
                break

            # 搜狗返回的是HTML，不是JSON
            html = resp.text
            if "用户您好，您的访问过于频繁" in html or "antispider" in html:
                logger.warning("[weixin] 触发反爬限制，停止采集")
                break

            # 解析HTML提取文章列表
            articles = self._parse_search_results(html)
            if not articles:
                break

            for article in articles:
                if len(results) >= limit:
                    break
                results.append(article)

            page += 1
            if page > 10:  # 搜狗最多10页
                break

        return results

    def _parse_search_results(self, html: str) -> list[CrawlResult]:
        """解析搜狗微信搜索结果页"""
        results = []

        # 匹配文章块
        # 搜狗的HTML结构：每个结果在 <div class="txt-box"> 中
        pattern = r'<div class="txt-box">(.*?)</div>\s*</div>'
        blocks = re.findall(pattern, html, re.DOTALL)

        for block in blocks:
            try:
                # 提取标题
                title_match = re.search(r'<a[^>]*>(.*?)</a>', block)
                title = re.sub(r"<[^>]+>", "", title_match.group(1)) if title_match else ""

                # 提取摘要
                excerpt_match = re.search(r'<p class="txt-info">(.*?)</p>', block, re.DOTALL)
                excerpt = re.sub(r"<[^>]+>", "", excerpt_match.group(1)).strip() if excerpt_match else ""

                # 提取公众号名
                author_match = re.search(r'<a class="account"[^>]*>(.*?)</a>', block)
                author = re.sub(r"<[^>]+>", "", author_match.group(1)).strip() if author_match else ""

                # 提取链接
                link_match = re.search(r'href="([^"]+)"', block)
                url = link_match.group(1) if link_match else ""
                if url and not url.startswith("http"):
                    url = "https://weixin.sogou.com" + url

                if not title:
                    continue

                text = f"{title} {excerpt}".strip()

                results.append(CrawlResult(
                    platform="weixin",
                    content_id="",  # 搜狗不提供文章ID
                    text=text[:1000],
                    author=author,
                    publish_time="",
                    source_url=url,
                    keyword="",
                ))

            except Exception as e:
                logger.debug(f"[weixin] 解析单条结果失败: {e}")
                continue

        return results
