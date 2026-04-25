#!/usr/bin/env python3
"""
LLM识别模块 - 伪科普监测系统 MVP

对采集到的文本进行多阶段分析：
  1. 预筛：是否涉科？
  2. 科学主张提取
  3. 事实核查（与本地谣言知识库比对）
  4. 风险评估（关键词密度 + 模式匹配 + LLM综合判断）
  5. 分类
  6. 严重等级

用法：
    python analyzer.py --text "要分析的文本"
    python analyzer.py --file data/weibo_raw_2026-04-23.jsonl --output data/analysis_2026-04-23.jsonl
"""

import argparse
import json
import os
import re
import sys
import logging
from datetime import datetime
from typing import Optional

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


# ============================================================
# 关键词词典 - 从关键词库文档提取的核心词表
# ============================================================

# 涉科领域关键词（用于预筛：文本是否与科学/健康/食品相关）
SCIENCE_DOMAIN_KEYWORDS = [
    # 健康医疗
    "癌症", "致癌", "肿瘤", "高血压", "糖尿病", "脂肪肝", "痛风", "冠心病",
    "失眠", "帕金森", "抑郁症", "肥胖", "免疫", "过敏", "心梗", "中风",
    "肺癌", "胃癌", "肝癌", "肠癌", "乳腺癌", "猝死",
    # 食品安全
    "农药", "添加剂", "防腐剂", "亚硝酸盐", "甲醛", "重金属", "激素", "抗生素",
    "转基因", "地沟油", "食品安全", "食物中毒",
    # 营养保健
    "维生素", "蛋白质", "胶原蛋白", "补钙", "排毒", "养生", "保健",
    "免疫力", "抵抗力", "偏方", "秘方", "中药",
    # 科技概念
    "量子", "纳米", "干细胞", "基因", "辐射", "5G", "微波", "电磁波",
    "负离子", "远红外", "磁场", "频率",
    # 疫苗
    "疫苗", "接种", "病毒", "细菌", "感染",
    # 食品相关（食品安全谣言高频词）
    "中毒", "有毒", "相克", "不能吃", "不能一起吃", "致癌物",
    "食物", "饮食", "吃了会", "营养",
]

# 恐惧营销词
FEAR_WORDS = [
    "致癌", "有毒", "中毒", "有害", "毒素", "污染", "致死", "危险",
    "隐形杀手", "无声杀手", "埋下祸根", "器官衰竭", "猝死",
    "太可怕了", "吓死了", "难以置信", "震撼", "颠覆认知",
    "不知道后果多严重", "专家都沉默了", "有人在隐瞒",
]

# 紧迫感词
URGENCY_WORDS = [
    "必须", "立即", "赶快", "不能再等", "错过就后悔", "千万别",
    "必看", "转发拯救", "不转不是人", "转发救人",
    "最后机会", "再也不能",
]

# 绝对化词
ABSOLUTE_WORDS = [
    "100%", "百分百", "零风险", "无副作用", "永久", "彻底",
    "一劳永逸", "包治百病", "根治", "一招治好",
    "立竿见影", "快速见效", "只有", "只能", "就是", "完全是",
    "全是", "都是", "必然导致", "唯一原因",
]

# 虚假权威词
FAKE_AUTHORITY_WORDS = [
    "某研究发现", "某大学研究", "研究表明", "据说", "听说",
    "民间偏方", "秘方", "有医生说", "医学界发现",
    "国际研究显示", "欧美研究", "某知名医院",
    "某权威机构证实", "某协会认证",
]

# 虚假见证词
FAKE_TESTIMONY_WORDS = [
    "我亲眼所见", "我身边", "我的朋友", "我妈用过", "我爸坚持吃",
    "真实案例", "亲身经历", "用过的人都说好",
    "99%用户好评", "反馈火爆", "已有\\d+万人购买",
]

# 科学概念滥用词（在非专业语境使用）
SCIENCE_ABUSE_WORDS = [
    "量子能量", "量子治疗", "量子芯片", "量子纠缠", "量子养生",
    "纳米技术", "纳米养生", "纳米水", "生物频率", "能量波", "磁场能量",
    "干细胞修复", "细胞唤醒", "细胞活化", "基因修复", "DNA激活",
    "负离子治病", "远红外排毒",
]

# 科学概念滥用组合检测：当多个高端科学词同时出现在非专业语境时触发
SCIENCE_BUZZWORDS = ["量子", "纳米", "干细胞", "基因", "负离子", "远红外", "石墨烯", "磁场"]

# 夸大效能词
EXAGGERATION_WORDS = [
    "革命性", "突破性", "首创", "从未有过", "世界首次",
    "独家配方", "黑科技", "最新科技", "世界顶级",
    "100%有效", "48小时改善", "7天显著", "30天蜕变",
    "90天完美", "年轻10岁", "逆龄", "返老还童",
]

# 营销词
MARKETING_WORDS = [
    "购买链接", "代理招募", "分销", "加盟", "限时优惠",
    "今日特价", "库存有限", "预约抢购", "会员专享",
    "拼团", "砍价", "邀请有奖", "转发返利",
    "正品保证", "假一赔十", "官方旗舰店",
]

# 食品相克触发词
FOOD_CLASH_WORDS = [
    "同吃会中毒", "一起吃致癌", "相克", "相冲", "搭配禁忌",
    "不能混吃", "会产生毒素", "不能同吃", "一起吃会",
]

# 伪科普分类
CATEGORIES = {
    "cognitive_bias": "认知误区",       # 对科学概念的错误理解
    "recycled_rumor": "冷饭热炒",       # 反复出现的已辟谣内容
    "new_rumor": "新发谣言",            # 新出现的虚假科学声称
    "pseudo_science": "伪科普",         # 包装成科普的商业/诈骗内容
}

# 伪科普子类型
PSEUDO_SCIENCE_SUBTYPES = {
    "fraud": "电诈属性",
    "reputation_attack": "风评属性",
    "cult": "邪教属性",
    "marketing": "营销属性",
}

# 严重等级
SEVERITY_LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


# ============================================================
# 阶段1：预筛 - 是否涉科
# ============================================================

def is_science_related(text: str) -> tuple[bool, list[str]]:
    """
    快速判断文本是否涉及科学/健康/食品等领域。
    纯Python实现，不依赖LLM。

    参数：
        text: 待检测文本

    返回：
        (是否涉科, 命中的领域关键词列表)
    """
    if not text:
        return False, []

    text_lower = text.lower()
    matched = []
    for kw in SCIENCE_DOMAIN_KEYWORDS:
        if kw.lower() in text_lower:
            matched.append(kw)

    return len(matched) >= 1, matched


# ============================================================
# 阶段2：关键词密度与模式匹配
# ============================================================

def count_keyword_hits(text: str, keyword_list: list[str]) -> tuple[int, list[str]]:
    """统计文本中命中的关键词数量和具体词"""
    text_lower = text.lower()
    hits = []
    for kw in keyword_list:
        # 支持正则表达式关键词
        if "\\" in kw:
            try:
                if re.search(kw, text, re.IGNORECASE):
                    hits.append(kw)
            except re.error:
                if kw.lower() in text_lower:
                    hits.append(kw)
        else:
            if kw.lower() in text_lower:
                hits.append(kw)
    return len(hits), hits


def compute_keyword_density(text: str) -> dict:
    """
    计算各类关键词的命中情况和密度。

    返回：
        {
            "fear": {"count": N, "hits": [...], "density": float},
            "urgency": {...},
            "absolute": {...},
            "fake_authority": {...},
            "fake_testimony": {...},
            "science_abuse": {...},
            "exaggeration": {...},
            "marketing": {...},
            "food_clash": {...},
        }
    """
    # 按字符计算粗略词数（中文按2字一词估算）
    char_count = len(text)
    word_count = max(char_count / 2, 1)

    result = {}
    categories = {
        "fear": FEAR_WORDS,
        "urgency": URGENCY_WORDS,
        "absolute": ABSOLUTE_WORDS,
        "fake_authority": FAKE_AUTHORITY_WORDS,
        "fake_testimony": FAKE_TESTIMONY_WORDS,
        "science_abuse": SCIENCE_ABUSE_WORDS,
        "exaggeration": EXAGGERATION_WORDS,
        "marketing": MARKETING_WORDS,
        "food_clash": FOOD_CLASH_WORDS,
    }

    for cat_name, kw_list in categories.items():
        count, hits = count_keyword_hits(text, kw_list)
        result[cat_name] = {
            "count": count,
            "hits": hits,
            "density": round(count / word_count * 100, 2),
        }

    # 科学概念组合滥用检测：多个高端科学词在非专业语境堆叠
    buzzword_hits = [bw for bw in SCIENCE_BUZZWORDS if bw in text]
    if len(buzzword_hits) >= 2:
        # 多个科学流行词堆叠，补充到science_abuse
        result["science_abuse"]["count"] += len(buzzword_hits)
        result["science_abuse"]["hits"].extend([f"[组合]{'+'.join(buzzword_hits)}"])
        result["science_abuse"]["density"] = round(
            result["science_abuse"]["count"] / word_count * 100, 2
        )

    return result


# ============================================================
# 阶段3：规则引擎 - 模式匹配
# ============================================================

def apply_rules(text: str, kw_stats: dict) -> list[dict]:
    """
    应用组合规则进行模式匹配。

    返回触发的规则列表：
        [{"rule_id": "R1", "name": "...", "severity": "...", "confidence": float, "detail": "..."}]
    """
    triggered = []

    # R1: 恐惧营销模式
    # 恐惧词>2 + 紧迫感词 + (产品推荐或链接)
    if kw_stats["fear"]["count"] >= 2 and kw_stats["urgency"]["count"] >= 1:
        if kw_stats["marketing"]["count"] >= 1:
            triggered.append({
                "rule_id": "R1",
                "name": "恐惧营销模式",
                "severity": "CRITICAL",
                "confidence": 0.95,
                "detail": f"恐惧词({kw_stats['fear']['count']}个) + 紧迫感 + 营销词",
            })
        else:
            triggered.append({
                "rule_id": "R1",
                "name": "恐惧营销模式(无营销词)",
                "severity": "HIGH",
                "confidence": 0.80,
                "detail": f"恐惧词({kw_stats['fear']['count']}个) + 紧迫感",
            })

    # R2: 权威虚构 + 见证堆砌
    if kw_stats["fake_authority"]["count"] >= 1 and kw_stats["fake_testimony"]["count"] >= 1:
        severity = "CRITICAL" if kw_stats["fake_testimony"]["count"] >= 3 else "HIGH"
        triggered.append({
            "rule_id": "R2",
            "name": "权威虚构+见证堆砌",
            "severity": severity,
            "confidence": 0.90,
            "detail": f"虚假权威({kw_stats['fake_authority']['count']}个) + 见证({kw_stats['fake_testimony']['count']}个)",
        })

    # R3: 科学滥用 + 功效夸大
    if kw_stats["science_abuse"]["count"] >= 1 and kw_stats["exaggeration"]["count"] >= 1:
        severity = "CRITICAL" if kw_stats["absolute"]["count"] >= 1 else "HIGH"
        triggered.append({
            "rule_id": "R3",
            "name": "科学滥用+功效夸大",
            "severity": severity,
            "confidence": 0.98 if severity == "CRITICAL" else 0.88,
            "detail": f"科学概念滥用({kw_stats['science_abuse']['hits']}) + 夸大效能",
        })

    # R4: 因果简化 + 绝对化
    if kw_stats["absolute"]["count"] >= 2:
        has_disease_mention = any(
            d in text for d in ["癌症", "糖尿病", "心脏病", "高血压", "脂肪肝", "痛风"]
        )
        if has_disease_mention:
            triggered.append({
                "rule_id": "R4",
                "name": "因果简化+绝对化",
                "severity": "HIGH",
                "confidence": 0.92,
                "detail": f"绝对化词({kw_stats['absolute']['count']}个) + 疾病关联",
            })

    # R5: 食品相克谣言
    if kw_stats["food_clash"]["count"] >= 1:
        triggered.append({
            "rule_id": "R5",
            "name": "食品相克谣言",
            "severity": "MEDIUM",
            "confidence": 0.85,
            "detail": f"食品相克触发词: {kw_stats['food_clash']['hits']}",
        })

    # R6: 纯营销导向（健康/科学 + 营销）
    if kw_stats["marketing"]["count"] >= 2:
        triggered.append({
            "rule_id": "R6",
            "name": "营销导向内容",
            "severity": "HIGH",
            "confidence": 0.85,
            "detail": f"营销词({kw_stats['marketing']['count']}个): {kw_stats['marketing']['hits']}",
        })

    return triggered


# ============================================================
# 阶段4：事实核查 - 与谣言知识库比对
# ============================================================

def load_knowledge_base(kb_path: str) -> dict:
    """加载本地谣言知识库"""
    if not os.path.exists(kb_path):
        logger.warning(f"谣言知识库不存在: {kb_path}")
        return {}

    try:
        with open(kb_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("articles", {}) if isinstance(data, dict) else {}
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"谣言知识库加载失败: {e}")
        return {}


def check_against_knowledge_base(text: str, kb: dict) -> list[dict]:
    """
    将文本与谣言知识库比对，查找已知辟谣。
    使用简单的关键词重叠度匹配。

    参数：
        text: 待检查文本
        kb: 谣言知识库（URL -> 文章信息）

    返回：
        匹配到的已知辟谣列表
    """
    if not kb:
        return []

    matches = []
    text_lower = text.lower()

    # 对文本做简单分词（按标点和空格切分）
    text_tokens = set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]+\d*", text_lower))

    for url, article in kb.items():
        title = article.get("title", "").lower()
        summary = article.get("content_summary", "").lower()
        keywords = [k.lower() for k in article.get("keywords", [])]

        # 计算关键词重叠度
        article_tokens = set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]+\d*", title + " " + summary))
        article_tokens.update(keywords)

        if not article_tokens:
            continue

        overlap = text_tokens & article_tokens
        overlap_ratio = len(overlap) / max(len(article_tokens), 1)

        # 阈值：重叠度 > 15% 视为相关
        if overlap_ratio > 0.15 and len(overlap) >= 3:
            matches.append({
                "title": article.get("title", ""),
                "url": url,
                "overlap_keywords": list(overlap)[:10],
                "overlap_ratio": round(overlap_ratio, 3),
                "expert": article.get("expert", ""),
            })

    # 按重叠度排序
    matches.sort(key=lambda x: x["overlap_ratio"], reverse=True)
    return matches[:5]  # 最多返回5条


# ============================================================
# 阶段5：风险评分计算
# ============================================================

def compute_risk_score(kw_stats: dict, rules: list[dict], kb_matches: list[dict], config: dict) -> float:
    """
    综合计算风险得分（0-10分制）。

    参数：
        kw_stats: 关键词统计
        rules: 触发的规则
        kb_matches: 知识库匹配结果
        config: 配置

    返回：
        风险得分（0-10）
    """
    weights = config.get("analyzer", {}).get("weights", {})

    score = 0.0

    # 关键词维度得分（每个维度0-10分）
    fear_score = min(kw_stats["fear"]["count"] * 2.5, 10)
    urgency_score = min(kw_stats["urgency"]["count"] * 3.0, 10)
    absolute_score = min(kw_stats["absolute"]["count"] * 3.0, 10)
    authority_score = min(kw_stats["fake_authority"]["count"] * 3.5, 10)
    marketing_score = min(kw_stats["marketing"]["count"] * 3.0, 10)
    testimony_score = min(kw_stats["fake_testimony"]["count"] * 3.0, 10)

    score += fear_score * weights.get("fear_words", 0.30)
    score += urgency_score * 0.20  # 紧迫感也要计入
    score += absolute_score * weights.get("absolute_words", 0.25)
    score += authority_score * weights.get("fake_authority", 0.25)
    score += marketing_score * weights.get("product_link", 0.20)
    score += testimony_score * weights.get("testimony", 0.15)

    # 科学概念滥用加分
    if kw_stats["science_abuse"]["count"] > 0:
        score += min(kw_stats["science_abuse"]["count"] * 2.0, 3)

    # 夸大效能加分
    if kw_stats["exaggeration"]["count"] > 0:
        score += min(kw_stats["exaggeration"]["count"] * 1.5, 3)

    # 规则触发加分（规则引擎是核心信号，权重要够大）
    for rule in rules:
        if rule["severity"] == "CRITICAL":
            score += 4.0
        elif rule["severity"] == "HIGH":
            score += 2.5
        elif rule["severity"] == "MEDIUM":
            score += 1.0

    # 知识库匹配加分（已有辟谣的内容风险更高，说明是冷饭热炒）
    if kb_matches:
        best_overlap = kb_matches[0]["overlap_ratio"]
        score += best_overlap * 4.0

    # 归一化到0-10
    return round(min(score, 10.0), 2)


def determine_severity(risk_score: float, rules: list[dict], config: dict) -> str:
    """
    根据风险得分和规则触发结果确定严重等级。
    规则引擎的CRITICAL/HIGH判定可以直接提升等级。
    """
    thresholds = config.get("analyzer", {}).get("risk_thresholds", {})

    # 先根据分数判定
    if risk_score >= thresholds.get("critical", 8.0):
        level = "CRITICAL"
    elif risk_score >= thresholds.get("high", 6.0):
        level = "HIGH"
    elif risk_score >= thresholds.get("medium", 4.0):
        level = "MEDIUM"
    else:
        level = "LOW"

    # 规则引擎结果可以向上提升等级（不能降低）
    level_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    for rule in rules:
        rule_level = rule.get("severity", "LOW")
        if level_order.get(rule_level, 0) > level_order.get(level, 0):
            level = rule_level

    return level


# ============================================================
# 阶段6：分类
# ============================================================

def classify_content(
    text: str,
    kw_stats: dict,
    rules: list[dict],
    kb_matches: list[dict],
) -> dict:
    """
    对内容进行分类。

    返回：
        {"category": "...", "subtype": "...", "reason": "..."}
    """
    # 优先判断：有知识库匹配 → 冷饭热炒
    if kb_matches and kb_matches[0]["overlap_ratio"] > 0.25:
        return {
            "category": "recycled_rumor",
            "category_cn": "冷饭热炒",
            "subtype": "",
            "reason": f"与已知辟谣文章高度相关: {kb_matches[0]['title']}",
        }

    # 有营销词 → 伪科普（营销属性）
    if kw_stats["marketing"]["count"] >= 2:
        subtype = "marketing"
        # 检查是否有诈骗特征
        fraud_signals = ["免费领", "加微信", "扫码", "转账", "汇款", "点击链接"]
        if any(s in text for s in fraud_signals):
            subtype = "fraud"

        return {
            "category": "pseudo_science",
            "category_cn": "伪科普",
            "subtype": subtype,
            "subtype_cn": PSEUDO_SCIENCE_SUBTYPES.get(subtype, ""),
            "reason": f"包含明显营销/推广特征: {kw_stats['marketing']['hits']}",
        }

    # 科学概念滥用 → 伪科普
    if kw_stats["science_abuse"]["count"] >= 1:
        return {
            "category": "pseudo_science",
            "category_cn": "伪科普",
            "subtype": "marketing",
            "subtype_cn": "营销属性",
            "reason": f"滥用科学概念: {kw_stats['science_abuse']['hits']}",
        }

    # 绝对化+恐惧 → 认知误区
    if kw_stats["absolute"]["count"] >= 1 and kw_stats["fear"]["count"] >= 1:
        return {
            "category": "cognitive_bias",
            "category_cn": "认知误区",
            "subtype": "",
            "reason": "使用绝对化表述传播恐惧",
        }

    # 食品相克 → 认知误区
    if kw_stats["food_clash"]["count"] >= 1:
        return {
            "category": "cognitive_bias",
            "category_cn": "认知误区",
            "subtype": "",
            "reason": "食品相克类误导信息",
        }

    # 虚假权威 → 新发谣言
    if kw_stats["fake_authority"]["count"] >= 1:
        return {
            "category": "new_rumor",
            "category_cn": "新发谣言",
            "subtype": "",
            "reason": f"引用虚假权威: {kw_stats['fake_authority']['hits']}",
        }

    # 默认
    return {
        "category": "unknown",
        "category_cn": "待定",
        "subtype": "",
        "reason": "未匹配到明确分类模式",
    }


# ============================================================
# LLM调用模块（占位实现，可接入任何OpenAI兼容API）
# ============================================================

def call_llm(
    prompt: str,
    system_prompt: str = "",
    config: Optional[dict] = None,
) -> Optional[str]:
    """
    调用OpenAI兼容的LLM API进行分析。
    如果API Key未配置或调用失败，返回None（系统回退到纯规则引擎）。

    参数：
        prompt: 用户提示词
        system_prompt: 系统提示词
        config: LLM配置

    返回：
        LLM回复文本或None
    """
    llm_config = (config or {}).get("llm", {})
    api_key = llm_config.get("api_key", "")
    api_base = llm_config.get("api_base", "https://api.openai.com/v1")
    model = llm_config.get("model", "gpt-4o-mini")
    timeout = llm_config.get("timeout", 60)
    max_tokens = llm_config.get("max_tokens", 2048)
    temperature = llm_config.get("temperature", 0.1)

    # 检查API Key是否有效
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        logger.debug("LLM API Key未配置，跳过LLM调用")
        return None

    url = f"{api_base.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except requests.RequestException as e:
        logger.warning(f"LLM调用失败: {e}")
        return None
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        logger.warning(f"LLM响应解析失败: {e}")
        return None


def llm_analyze(
    text: str,
    kw_stats: dict,
    rules: list[dict],
    kb_matches: list[dict],
    config: Optional[dict] = None,
) -> Optional[dict]:
    """
    使用LLM进行深度分析（可选，API未配置时跳过）。

    返回LLM的分析结果字典或None。
    """
    system_prompt = """你是一个专业的伪科普内容识别专家。你的任务是分析给定的文本，判断其是否为伪科普/谣言/误导性内容。

请以JSON格式返回分析结果，包含以下字段：
- science_claims: 文本中的科学断言列表
- factual_errors: 事实错误列表（如果有）
- misleading_techniques: 使用的误导技术（如恐惧营销、虚假权威等）
- risk_assessment: 风险评估说明
- suggested_category: 建议分类（认知误区/冷饭热炒/新发谣言/伪科普）
- suggested_severity: 建议严重等级（LOW/MEDIUM/HIGH/CRITICAL）
- confidence: 判断置信度（0-1）
- explanation: 详细解释

只返回JSON，不要其他内容。"""

    # 构造上下文
    context_parts = [f"## 待分析文本\n{text}\n"]

    if rules:
        rule_desc = "\n".join([f"- {r['rule_id']}: {r['name']} ({r['severity']})" for r in rules])
        context_parts.append(f"## 规则引擎触发结果\n{rule_desc}\n")

    if kb_matches:
        kb_desc = "\n".join([f"- {m['title']} (重叠度: {m['overlap_ratio']})" for m in kb_matches])
        context_parts.append(f"## 谣言知识库匹配\n{kb_desc}\n")

    prompt = "\n".join(context_parts)
    prompt += "\n请分析以上文本，返回JSON格式结果。"

    response = call_llm(prompt, system_prompt, config)
    if not response:
        return None

    # 尝试解析JSON
    try:
        # 移除可能的markdown代码块标记
        response = re.sub(r"^```(?:json)?\s*", "", response.strip())
        response = re.sub(r"\s*```$", "", response.strip())
        return json.loads(response)
    except json.JSONDecodeError:
        logger.warning("LLM返回内容无法解析为JSON")
        return {"raw_response": response}


# ============================================================
# 主分析函数
# ============================================================

def analyze_text(
    text: str,
    config: Optional[dict] = None,
    kb: Optional[dict] = None,
) -> dict:
    """
    对单条文本进行完整的伪科普分析。

    参数：
        text: 待分析文本
        config: 系统配置
        kb: 谣言知识库（可选）

    返回：
        结构化分析结果字典
    """
    if config is None:
        config = load_config()

    result = {
        "text": text[:200] + "..." if len(text) > 200 else text,
        "text_length": len(text),
        "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "is_science_related": False,
        "science_keywords": [],
        "keyword_stats": {},
        "triggered_rules": [],
        "kb_matches": [],
        "risk_score": 0.0,
        "severity": "LOW",
        "classification": {},
        "llm_analysis": None,
        "requires_review": False,
    }

    # === 阶段1：预筛 ===
    is_science, science_kws = is_science_related(text)
    result["is_science_related"] = is_science
    result["science_keywords"] = science_kws

    if not is_science:
        logger.info("文本不涉科，跳过后续分析")
        result["severity"] = "SKIP"
        return result

    # === 阶段2：关键词密度分析 ===
    kw_stats = compute_keyword_density(text)
    result["keyword_stats"] = kw_stats

    # === 阶段3：规则引擎 ===
    rules = apply_rules(text, kw_stats)
    result["triggered_rules"] = rules

    # === 阶段4：事实核查 ===
    if kb is None:
        kb_path = config.get("output", {}).get("knowledge_base", "data/rumor_knowledge_base.json")
        kb = load_knowledge_base(kb_path)
    kb_matches = check_against_knowledge_base(text, kb)
    result["kb_matches"] = kb_matches

    # === 阶段5：风险评分 ===
    risk_score = compute_risk_score(kw_stats, rules, kb_matches, config)
    severity = determine_severity(risk_score, rules, config)
    result["risk_score"] = risk_score
    result["severity"] = severity

    # === 阶段6：分类 ===
    classification = classify_content(text, kw_stats, rules, kb_matches)
    result["classification"] = classification

    # === 可选：LLM深度分析 ===
    # 只对 MEDIUM 以上的内容调用LLM（节省API调用）
    if severity in ("MEDIUM", "HIGH", "CRITICAL"):
        llm_result = llm_analyze(text, kw_stats, rules, kb_matches, config)
        result["llm_analysis"] = llm_result

    # 需要人工审核的标记
    result["requires_review"] = severity in ("MEDIUM",) or (
        severity == "HIGH" and not rules  # 高风险但没有明确规则触发的需要人审
    )

    return result


def analyze_file(
    input_file: str,
    output_file: str,
    config_path: str = DEFAULT_CONFIG_PATH,
    text_field: str = "text",
) -> int:
    """
    批量分析JSONL文件中的文本。

    参数：
        input_file: 输入JSONL文件路径（每行一个JSON对象，包含text字段）
        output_file: 输出JSONL文件路径
        config_path: 配置文件路径
        text_field: JSON中文本字段名

    返回：
        分析的条目数
    """
    config = load_config(config_path)
    kb_path = config.get("output", {}).get("knowledge_base", "data/rumor_knowledge_base.json")
    kb = load_knowledge_base(kb_path)

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

    count = 0
    flagged = 0

    with open(input_file, "r", encoding="utf-8") as fin, \
         open(output_file, "w", encoding="utf-8") as fout:

        for line_num, line in enumerate(fin, 1):
            line = line.strip()
            if not line:
                continue

            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                logger.warning(f"第 {line_num} 行JSON解析失败，跳过")
                continue

            text = item.get(text_field, "")
            if not text:
                continue

            logger.info(f"分析第 {line_num} 条: {text[:50]}...")
            analysis = analyze_text(text, config=config, kb=kb)

            # 合并原始数据和分析结果
            output_item = {**item, "analysis": analysis}
            fout.write(json.dumps(output_item, ensure_ascii=False) + "\n")

            count += 1
            if analysis["severity"] not in ("LOW", "SKIP"):
                flagged += 1

    logger.info(f"分析完成: 共 {count} 条，标记 {flagged} 条异常")
    return count


# ============================================================
# 命令行入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="伪科普内容LLM识别分析工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
    # 分析单条文本
    python analyzer.py --text "量子能量水，100%有效，永久改善睡眠"

    # 批量分析JSONL文件
    python analyzer.py --file data/weibo_raw_2026-04-23.jsonl --output data/analysis_2026-04-23.jsonl
        """,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", help="待分析的文本内容")
    group.add_argument("--file", help="待分析的JSONL文件路径")

    parser.add_argument(
        "--output",
        help="输出文件路径（批量模式必填）",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help="配置文件路径（默认: config.yaml）",
    )

    args = parser.parse_args()

    if args.text:
        # 单条分析模式
        config = load_config(args.config)
        result = analyze_text(args.text, config=config)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.file:
        # 批量分析模式
        if not args.output:
            date_str = datetime.now().strftime("%Y-%m-%d")
            args.output = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "data",
                f"analysis_{date_str}.jsonl",
            )
        count = analyze_file(args.file, args.output, config_path=args.config)
        print(f"\n✅ 分析完成: {count} 条，输出到: {args.output}")


if __name__ == "__main__":
    main()
