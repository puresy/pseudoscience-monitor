#!/usr/bin/env python3
"""
LLM 成本追踪器 - 伪科普监测系统

追踪 API 调用次数和 token 使用量，防止超支。
"""

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class CallRecord:
    """单次调用记录"""
    timestamp: float
    model: str
    input_tokens: int
    output_tokens: int
    cost: float
    success: bool
    purpose: str = ""  # 分类用途


class CostTracker:
    """成本追踪器"""

    def __init__(self, log_dir: str = "logs", daily_limit: float = 10.0, run_limit: int = 100):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.daily_limit = daily_limit  # 每日成本上限（元）
        self.run_limit = run_limit  # 单次运行调用上限
        self.records: list[CallRecord] = []
        self._run_count = 0
        self._session_file = self.log_dir / f"cost_{datetime.now().strftime('%Y%m%d')}.jsonl"

    def log_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        success: bool,
        purpose: str = "",
    ):
        """记录一次 API 调用"""
        record = CallRecord(
            timestamp=time.time(),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            success=success,
            purpose=purpose,
        )
        self.records.append(record)
        self._run_count += 1

        # 追加到日志文件
        with open(self._session_file, "a") as f:
            f.write(json.dumps({
                "ts": record.timestamp,
                "model": record.model,
                "in": record.input_tokens,
                "out": record.output_tokens,
                "cost": record.cost,
                "ok": record.success,
                "purpose": record.purpose,
            }) + "\n")

    def can_call(self) -> bool:
        """检查是否允许继续调用"""
        if self._run_count >= self.run_limit:
            return False
        if self.daily_cost >= self.daily_limit:
            return False
        return True

    @property
    def daily_cost(self) -> float:
        """今日总成本"""
        today_start = datetime.now().replace(hour=0, minute=0, second=0).timestamp()
        return sum(r.cost for r in self.records if r.timestamp >= today_start)

    @property
    def run_count(self) -> int:
        """本次运行调用次数"""
        return self._run_count

    def summary(self) -> dict:
        """成本摘要"""
        total_in = sum(r.input_tokens for r in self.records)
        total_out = sum(r.output_tokens for r in self.records)
        success = sum(1 for r in self.records if r.success)
        fail = sum(1 for r in self.records if not r.success)
        return {
            "total_calls": len(self.records),
            "run_calls": self._run_count,
            "success": success,
            "failed": fail,
            "input_tokens": total_in,
            "output_tokens": total_out,
            "total_cost": sum(r.cost for r in self.records),
            "daily_cost": self.daily_cost,
            "daily_limit": self.daily_limit,
            "run_limit": self.run_limit,
        }

    def format_summary(self) -> str:
        """格式化摘要"""
        s = self.summary()
        return (
            f"API调用: {s['run_calls']}/{s['run_limit']}次 | "
            f"成功: {s['success']} | 失败: {s['failed']} | "
            f"Token: {s['input_tokens']+s['output_tokens']} | "
            f"今日成本: {s['daily_cost']:.2f}/{s['daily_limit']:.2f}元"
        )
