#!/usr/bin/env python3
"""
配置管理 - 伪科普监测系统

统一管理所有配置项，支持环境变量覆盖。
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


CONFIG_DIR = Path(__file__).parent / "config"
DATA_DIR = Path(__file__).parent / "data"
LOG_DIR = Path(__file__).parent / "logs"


@dataclass
class LLMConfig:
    """LLM 配置"""
    api_key: str = ""
    api_url: str = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    model: str = "glm-4-flash"
    max_tokens: int = 512
    temperature: float = 0.3
    timeout: int = 30
    max_calls_per_run: int = 50  # 单次运行最大调用次数
    cost_per_1k_tokens: float = 0.0  # 免费模型


@dataclass
class CrawlerConfig:
    """采集器配置"""
    request_timeout: int = 15
    max_retries: int = 3
    retry_delay: float = 2.0
    rate_limit_delay: float = 1.0  # 请求间隔
    proxy: str = ""  # HTTP 代理
    cookie_dir: str = str(CONFIG_DIR / "cookies")
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )


@dataclass
class AnalyzerConfig:
    """分析器配置"""
    risk_threshold: float = 0.5  # GRAY_ZONE 阈值
    llm_threshold: float = 0.4  # 触发 LLM 的阈值
    kb_match_threshold: float = 0.15  # 知识库匹配阈值
    source_weight_verified: float = 0.5  # 认证用户风险分权重
    max_text_length: int = 2000  # 分析文本最大长度


@dataclass
class PropagationConfig:
    """传播分析配置"""
    similarity_threshold: float = 0.6
    min_cluster_size: int = 2
    matrix_min_posts: int = 3
    matrix_min_similarity: float = 0.6


@dataclass
class ReportConfig:
    """报告配置"""
    top_events: int = 5
    include_raw_data: bool = False
    output_format: str = "markdown"  # markdown / json


@dataclass
class SystemConfig:
    """系统总配置"""
    llm: LLMConfig = field(default_factory=LLMConfig)
    crawler: CrawlerConfig = field(default_factory=CrawlerConfig)
    analyzer: AnalyzerConfig = field(default_factory=AnalyzerConfig)
    propagation: PropagationConfig = field(default_factory=PropagationConfig)
    report: ReportConfig = field(default_factory=ReportConfig)

    # 全局
    log_level: str = "INFO"
    data_dir: str = str(DATA_DIR)
    log_dir: str = str(LOG_DIR)
    knowledge_base: str = str(DATA_DIR / "rumor_knowledge_base.json")


def load_config(config_path: Optional[str] = None) -> SystemConfig:
    """加载配置，支持 JSON 文件 + 环境变量覆盖"""
    config = SystemConfig()

    # 从文件加载
    if config_path and os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 简单的字段覆盖
        if "llm" in data:
            for k, v in data["llm"].items():
                if hasattr(config.llm, k):
                    setattr(config.llm, k, v)
        if "crawler" in data:
            for k, v in data["crawler"].items():
                if hasattr(config.crawler, k):
                    setattr(config.crawler, k, v)
        if "analyzer" in data:
            for k, v in data["analyzer"].items():
                if hasattr(config.analyzer, k):
                    setattr(config.analyzer, k, v)

    # 环境变量覆盖
    if os.environ.get("ZHIPU_API_KEY"):
        config.llm.api_key = os.environ["ZHIPU_API_KEY"]
    if os.environ.get("HTTP_PROXY"):
        config.crawler.proxy = os.environ["HTTP_PROXY"]
    if os.environ.get("LOG_LEVEL"):
        config.log_level = os.environ["LOG_LEVEL"]

    return config


# 默认配置实例
DEFAULT_CONFIG = load_config()
