#!/usr/bin/env python3
"""
Cookie 管理器 - 伪科普监测系统

支持从文件加载、自动刷新、多平台管理。
"""

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class CookieEntry:
    """单条 Cookie"""
    platform: str
    cookie_str: str
    updated_at: float = 0.0
    expires_at: float = 0.0
    source: str = ""  # manual / browser / api

    @property
    def is_expired(self) -> bool:
        if self.expires_at <= 0:
            return False  # 未知过期时间，假设有效
        return time.time() > self.expires_at

    @property
    def age_hours(self) -> float:
        return (time.time() - self.updated_at) / 3600


class CookieManager:
    """Cookie 管理器"""

    def __init__(self, cookie_dir: str = "config/cookies"):
        self.cookie_dir = Path(cookie_dir)
        self.cookie_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, CookieEntry] = {}
        self._load_all()

    def _load_all(self):
        """从目录加载所有 cookie 文件"""
        for f in self.cookie_dir.glob("*.json"):
            try:
                with open(f, "r") as fh:
                    data = json.load(fh)
                entry = CookieEntry(**data)
                self._cache[entry.platform] = entry
            except Exception:
                continue
        # 也支持纯文本 .txt 文件（直接是 cookie 字符串）
        for f in self.cookie_dir.glob("*.txt"):
            platform = f.stem
            cookie_str = f.read_text().strip()
            if cookie_str:
                self._cache[platform] = CookieEntry(
                    platform=platform,
                    cookie_str=cookie_str,
                    updated_at=f.stat().st_mtime,
                    source="file",
                )

    def get(self, platform: str) -> Optional[str]:
        """获取指定平台的 cookie 字符串"""
        entry = self._cache.get(platform)
        if not entry:
            return None
        if entry.is_expired:
            return None
        return entry.cookie_str

    def set(self, platform: str, cookie_str: str, expires_hours: float = 24):
        """设置 cookie"""
        entry = CookieEntry(
            platform=platform,
            cookie_str=cookie_str,
            updated_at=time.time(),
            expires_at=time.time() + expires_hours * 3600 if expires_hours > 0 else 0,
            source="manual",
        )
        self._cache[platform] = entry
        # 持久化
        path = self.cookie_dir / f"{platform}.json"
        with open(path, "w") as f:
            json.dump({
                "platform": entry.platform,
                "cookie_str": entry.cookie_str,
                "updated_at": entry.updated_at,
                "expires_at": entry.expires_at,
                "source": entry.source,
            }, f, indent=2)

    def status(self) -> dict[str, dict]:
        """查看所有 cookie 状态"""
        result = {}
        for platform, entry in self._cache.items():
            result[platform] = {
                "has_cookie": bool(entry.cookie_str),
                "is_expired": entry.is_expired,
                "age_hours": round(entry.age_hours, 1),
                "source": entry.source,
            }
        return result

    def need_refresh(self, platform: str, warn_hours: float = 12) -> bool:
        """检查是否需要刷新（超过 warn_hours 未更新）"""
        entry = self._cache.get(platform)
        if not entry:
            return True
        return entry.age_hours > warn_hours
