#!/usr/bin/env python3
"""
跨平台采集器基类 - 伪科普监测系统

定义统一的采集接口和输出格式。
"""

import json
import logging
import os
import random
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class CrawlResult:
    """统一的采集结果格式"""

    def __init__(
        self,
        platform: str,
        content_id: str,
        text: str,
        author: str = "",
        author_id: str = "",
        publish_time: str = "",
        source_url: str = "",
        metrics: Optional[dict] = None,
        keyword: str = "",
        extra: Optional[dict] = None,
    ):
        self.platform = platform
        self.content_id = content_id
        self.text = text
        self.author = author
        self.author_id = author_id
        self.publish_time = publish_time
        self.source_url = source_url
        self.metrics = metrics or {}
        self.keyword = keyword
        self.extra = extra or {}
        self.crawl_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "content_id": self.content_id,
            "text": self.text,
            "author": self.author,
            "author_id": self.author_id,
            "publish_time": self.publish_time,
            "source_url": self.source_url,
            "metrics": self.metrics,
            "keyword": self.keyword,
            "crawl_time": self.crawl_time,
            **self.extra,
        }

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


class BaseCrawler(ABC):
    """跨平台采集器基类"""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.session = None
        self._rate_limit_delay = self.config.get("rate_limit_delay", 2.0)
        self._max_retries = self.config.get("max_retries", 3)

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """平台名称标识"""
        pass

    @abstractmethod
    def search(self, keyword: str, limit: int = 20) -> list[CrawlResult]:
        """
        按关键词搜索内容。

        Args:
            keyword: 搜索关键词
            limit: 返回结果数量上限

        Returns:
            CrawlResult 列表
        """
        pass

    def crawl_keywords(self, keywords: list[str], limit_per_keyword: int = 20) -> list[CrawlResult]:
        """
        批量关键词采集。

        Args:
            keywords: 关键词列表
            limit_per_keyword: 每个关键词采集数量

        Returns:
            所有采集结果
        """
        all_results = []
        for i, kw in enumerate(keywords):
            logger.info(f"[{self.platform_name}] 采集关键词 ({i+1}/{len(keywords)}): {kw}")
            try:
                results = self.search(kw, limit=limit_per_keyword)
                all_results.extend(results)
                logger.info(f"[{self.platform_name}] '{kw}' 采集到 {len(results)} 条")
            except Exception as e:
                logger.error(f"[{self.platform_name}] '{kw}' 采集失败: {e}")

            # 频率控制
            if i < len(keywords) - 1:
                delay = self._rate_limit_delay + random.uniform(0.5, 1.5)
                time.sleep(delay)

        logger.info(f"[{self.platform_name}] 总计采集 {len(all_results)} 条")
        return all_results

    def save_results(self, results: list[CrawlResult], output_path: str):
        """保存结果到 JSONL 文件"""
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for r in results:
                f.write(r.to_jsonl() + "\n")
        logger.info(f"[{self.platform_name}] 保存 {len(results)} 条到 {output_path}")

    def _get_session(self):
        """获取或创建 requests session"""
        if self.session is None:
            import requests
            self.session = requests.Session()
            self.session.headers.update({
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            })
        return self.session

    def _retry_request(self, url: str, **kwargs) -> Optional[requests.Response]:
        """带重试的 HTTP 请求"""
        import requests
        for attempt in range(self._max_retries):
            try:
                resp = self._get_session().get(url, timeout=15, **kwargs)
                if resp.status_code == 200:
                    return resp
                logger.warning(f"[{self.platform_name}] HTTP {resp.status_code} on {url}")
            except requests.RequestException as e:
                logger.warning(f"[{self.platform_name}] 请求失败 (attempt {attempt+1}): {e}")
            if attempt < self._max_retries - 1:
                time.sleep(2 ** attempt)
        return None
