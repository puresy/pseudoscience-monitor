#!/usr/bin/env python3
"""
B站采集器 - 伪科普监测系统

通过 B站搜索 API 采集视频信息。
"""

import json
import logging
import re
from typing import Optional
from urllib.parse import quote

from .base import BaseCrawler, CrawlResult

logger = logging.getLogger(__name__)


class BilibiliCrawler(BaseCrawler):
    """B站视频采集器"""

    SEARCH_API = "https://api.bilibili.com/x/web-interface/search/type"

    @property
    def platform_name(self) -> str:
        return "bilibili"

    def search(self, keyword: str, limit: int = 20) -> list[CrawlResult]:
        results = []
        page = 1
        per_page = min(limit, 50)

        while len(results) < limit:
            params = {
                "search_type": "video",
                "keyword": keyword,
                "page": page,
                "pagesize": per_page,
                "order": "totalrank",
            }

            headers = {
                "Referer": "https://search.bilibili.com/",
                "Origin": "https://search.bilibili.com",
            }

            resp = self._retry_request(self.SEARCH_API, params=params, headers=headers)
            if not resp:
                logger.warning(f"[bilibili] 搜索 '{keyword}' 第{page}页失败")
                break

            try:
                data = resp.json()
            except json.JSONDecodeError:
                logger.warning(f"[bilibili] JSON解析失败")
                break

            if data.get("code") != 0:
                logger.warning(f"[bilibili] API错误: {data.get('message', 'unknown')}")
                break

            items = data.get("data", {}).get("result", [])
            if not items:
                break

            for item in items:
                if len(results) >= limit:
                    break

                # 清理HTML标签
                title = re.sub(r"<[^>]+>", "", item.get("title", ""))
                description = item.get("description", "")

                result = CrawlResult(
                    platform="bilibili",
                    content_id=item.get("bvid", ""),
                    text=f"{title} {description}".strip(),
                    author=item.get("author", ""),
                    author_id=str(item.get("mid", "")),
                    publish_time=self._format_time(item.get("pubdate", 0)),
                    source_url=f"https://www.bilibili.com/video/{item.get('bvid', '')}",
                    metrics={
                        "play": item.get("play", 0),
                        "danmaku": item.get("video_review", 0),
                        "favorites": item.get("favorites", 0),
                        "like": item.get("like", 0),
                    },
                    keyword=keyword,
                    extra={
                        "duration": item.get("duration", ""),
                        "tag": item.get("tag", ""),
                    },
                )
                results.append(result)

            page += 1
            if len(items) < per_page:
                break

        return results

    def _format_time(self, timestamp: int) -> str:
        if not timestamp:
            return ""
        from datetime import datetime
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
