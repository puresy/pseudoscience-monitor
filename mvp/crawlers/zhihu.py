#!/usr/bin/env python3
"""
知乎采集器 - 伪科普监测系统

通过知乎搜索 API 采集回答内容。
"""

import json
import logging
import re
from typing import Optional
from urllib.parse import quote

from .base import BaseCrawler, CrawlResult

logger = logging.getLogger(__name__)


class ZhihuCrawler(BaseCrawler):
    """知乎回答采集器"""

    SEARCH_API = "https://www.zhihu.com/api/v4/search_v3"

    @property
    def platform_name(self) -> str:
        return "zhihu"

    def search(self, keyword: str, limit: int = 20) -> list[CrawlResult]:
        results = []
        offset = 0

        while len(results) < limit:
            params = {
                "t": "general",
                "q": keyword,
                "correction": 1,
                "offset": offset,
                "limit": min(20, limit - len(results)),
            }

            headers = {
                "Referer": "https://www.zhihu.com/search",
                "x-requested-with": "fetch",
            }

            resp = self._retry_request(self.SEARCH_API, params=params, headers=headers)
            if not resp:
                logger.warning(f"[zhihu] 搜索 '{keyword}' 失败")
                break

            try:
                data = resp.json()
            except json.JSONDecodeError:
                logger.warning(f"[zhihu] JSON解析失败")
                break

            items = data.get("data", [])
            if not items:
                break

            for item in items:
                if len(results) >= limit:
                    break

                obj = item.get("object", {})
                if item.get("type") not in ("answer", "article"):
                    continue

                # 提取内容
                content = obj.get("content", "") or obj.get("excerpt", "")
                content = re.sub(r"<[^>]+>", "", content)

                title = obj.get("question", {}).get("name", "") or obj.get("title", "")
                text = f"{title} {content}".strip()

                if not text:
                    continue

                # 提取作者
                author_info = obj.get("author", {})

                result = CrawlResult(
                    platform="zhihu",
                    content_id=str(obj.get("id", "")),
                    text=text[:1000],  # 截断过长内容
                    author=author_info.get("name", ""),
                    author_id=author_info.get("url_token", ""),
                    publish_time="",
                    source_url=f"https://www.zhihu.com/question/{obj.get('question', {}).get('id', '')}/answer/{obj.get('id', '')}" if item.get("type") == "answer" else f"https://zhuanlan.zhihu.com/p/{obj.get('id', '')}",
                    metrics={
                        "upvotes": obj.get("voteup_count", 0),
                        "comment_count": obj.get("comment_count", 0),
                    },
                    keyword=keyword,
                    extra={
                        "content_type": item.get("type", ""),
                    },
                )
                results.append(result)

            # 翻页
            paging = data.get("paging", {})
            if paging.get("is_end", True):
                break
            offset += 20

        return results
