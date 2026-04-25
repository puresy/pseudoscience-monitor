#!/usr/bin/env python3
"""
LLM识别模块 v3 - 伪科普监测系统 MVP

v3 核心变更：分类体系重构
  - 新增 content_type 层：PSEUDOSCIENCE / DEBUNKING / NORMAL_SCIENCE / NON_SCIENCE
  - severity 仅对 PSEUDOSCIENCE 有意义：CRITICAL / HIGH / MEDIUM
  - 非 PSEUDOSCIENCE 的内容 severity 统一为 NONE
  - 废弃 LOW 和 SKIP 等级

分析阶段：
  1. 预筛：是否涉科？
  2. 辟谣帖检测
  3. 关键词密度 + 模式匹配
  4. 规则引擎
  5. 事实核查（与本地谣言知识库比对）
  6. 风险评分
  7. 内容分类（content_type + severity）
  8. LLM二次判断（仅对规则引擎判定为可疑的内容）

用法：
    python analyzer_v3.py --text "要分析的文本"
    python analyzer_v3.py --file data/weibo_real_2026-04-23.jsonl --output data/analysis_v3_2026-04-24.jsonl
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
# v3 分类体系
# ============================================================

# 内容类型
CONTENT_TYPES = ["PSEUDOSCIENCE", "DEBUNKING", "NORMAL_SCIENCE", "NON_SCIENCE"]

# 风险等级（仅 PSEUDOSCIENCE 使用 CRITICAL/HIGH/MEDIUM，其余为 NONE）
SEVERITY_LEVELS = ["NONE", "MEDIUM", "HIGH", "CRITICAL"]

CONTENT_TYPE_CN = {
    "PSEUDOSCIENCE": "伪科普/谣言",
    "DEBUNKING": "辟谣内容",
    "NORMAL_SCIENCE": "正常科普",
    "NON_SCIENCE": "非科学内容",
}


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

# 辟谣/科普帖标识词
DEBUNK_WORDS = [
    "辟谣", "谣言", "别信", "不实", "假的", "科学辟谣", "科普中国", "真相是",
    "别再被谣言", "真相来了", "别再传了", "不是真的", "不可信", "没有科学依据",
    "其实是", "实际上", "澄清", "正确的说法", "科学解释", "科学事实",
    "食药监", "卫健委", "疾控中心", "世卫组织", "WHO",
    "别被骗", "防骗", "提醒大家", "12377",
]

# 辟谣账号关键词（用户名包含这些词的更可能是辟谣帖）
DEBUNK_ACCOUNT_KEYWORDS = [
    "辟谣", "科普", "科学", "营养师", "医生", "医学", "健康报",
    "卫健", "疾控", "食药",
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
# 阶段1.5：辟谣帖检测
# ============================================================

def is_debunking_post(text: str, username: str = "") -> tuple[bool, float]:
    """
    检测文本是否为辟谣/科普帖（引用谣言是为了反驳，而非传播）。

    返回：
        (是否辟谣帖, 置信度0-1)
    """
    if not text:
        return False, 0.0

    text_lower = text.lower()
    score = 0.0

    # 辟谣关键词命中
    debunk_hits = [w for w in DEBUNK_WORDS if w in text_lower]
    score += min(len(debunk_hits) * 0.25, 0.7)

    # 账号名包含辟谣/科普类关键词
    if username:
        for kw in DEBUNK_ACCOUNT_KEYWORDS:
            if kw in username:
                score += 0.2
                break

    # 典型辟谣句式（"其实...""真相是...""不是...而是..."）
    debunk_patterns = [
        r"真相[是：:].{2,}",
        r"其实[是，,].{2,}",
        r"不是.{2,}而是.{2,}",
        r"实际上.{2,}",
        r"别再被.{2,}骗",
        r"(科学|正确)[的地]?(说法|解释|做法)",
        r"#.*辟谣.*#",
        r"#.*真相.*#",
    ]
    for pattern in debunk_patterns:
        if re.search(pattern, text):
            score += 0.15

    is_debunk = score >= 0.4
    return is_debunk, round(min(score, 1.0), 2)


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
            ...
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

    # R1: 恐惧营销模式（恐惧词≥1 + 紧迫感≥1）
    # 排除逻辑：如果恐惧词命中但同时有明确的科学机构/研究引用，降低R1置信度
    _science_ref_words = [
        "央视", "世卫组织", "WHO", "研究表明", "研究发现", "研究显示",
        "卫健委", "疾控中心", "食药监", "中科院", "科学院",
        "国际癌症研究机构", "IARC", "柳叶刀", "Nature", "Science",
    ]
    _has_science_ref = any(ref in text for ref in _science_ref_words)

    if kw_stats["fear"]["count"] >= 1 and kw_stats["urgency"]["count"] >= 1:
        if kw_stats["marketing"]["count"] >= 1:
            r1_confidence = 0.95
            if _has_science_ref:
                r1_confidence = 0.65
            triggered.append({
                "rule_id": "R1",
                "name": "恐惧营销模式",
                "severity": "CRITICAL" if r1_confidence >= 0.80 else "HIGH",
                "confidence": r1_confidence,
                "detail": f"恐惧词({kw_stats['fear']['count']}个) + 紧迫感 + 营销词" + (" [有科学引用，置信度降低]" if _has_science_ref else ""),
            })
        else:
            r1_confidence = 0.80
            if _has_science_ref:
                r1_confidence = 0.50
            triggered.append({
                "rule_id": "R1",
                "name": "恐惧营销模式(无营销词)",
                "severity": "HIGH" if r1_confidence >= 0.70 else "MEDIUM",
                "confidence": r1_confidence,
                "detail": f"恐惧词({kw_stats['fear']['count']}个) + 紧迫感" + (" [有科学引用，置信度降低]" if _has_science_ref else ""),
            })

    # R2: 权威虚构（虚假权威≥1即可触发）
    if kw_stats["fake_authority"]["count"] >= 1:
        if kw_stats["fake_testimony"]["count"] >= 1:
            severity = "CRITICAL" if kw_stats["fake_testimony"]["count"] >= 3 else "HIGH"
            triggered.append({
                "rule_id": "R2",
                "name": "权威虚构+见证堆砌",
                "severity": severity,
                "confidence": 0.90,
                "detail": f"虚假权威({kw_stats['fake_authority']['count']}个) + 见证({kw_stats['fake_testimony']['count']}个)",
            })
        else:
            triggered.append({
                "rule_id": "R2",
                "name": "权威虚构",
                "severity": "MEDIUM",
                "confidence": 0.70,
                "detail": f"虚假权威({kw_stats['fake_authority']['count']}个)",
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

    # R4: 因果简化 + 绝对化（绝对化词≥1 + 疾病关联）
    if kw_stats["absolute"]["count"] >= 1:
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
    """
    if not kb:
        return []

    matches = []
    text_lower = text.lower()

    text_tokens = set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]+\d*", text_lower))

    for url, article in kb.items():
        title = article.get("title", "").lower()
        summary = article.get("content_summary", "").lower()
        keywords = [k.lower() for k in article.get("keywords", [])]

        article_tokens = set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]+\d*", title + " " + summary))
        article_tokens.update(keywords)

        if not article_tokens:
            continue

        overlap = text_tokens & article_tokens
        overlap_ratio = len(overlap) / max(len(article_tokens), 1)

        if overlap_ratio > 0.15 and len(overlap) >= 3:
            matches.append({
                "title": article.get("title", ""),
                "url": url,
                "overlap_keywords": list(overlap)[:10],
                "overlap_ratio": round(overlap_ratio, 3),
                "expert": article.get("expert", ""),
            })

    matches.sort(key=lambda x: x["overlap_ratio"], reverse=True)
    return matches[:5]


# ============================================================
# 阶段5：风险评分计算
# ============================================================

def compute_risk_score(kw_stats: dict, rules: list[dict], kb_matches: list[dict], config: dict) -> float:
    """
    综合计算风险得分（0-10分制）。
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
    score += urgency_score * 0.20
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

    # 规则触发加分
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

    return round(min(score, 10.0), 2)


def determine_rule_severity(risk_score: float, rules: list[dict], config: dict) -> str:
    """
    根据风险得分和规则触发结果确定规则引擎的初步严重等级。
    返回 CRITICAL / HIGH / MEDIUM / NONE。
    """
    thresholds = config.get("analyzer", {}).get("risk_thresholds", {})

    if risk_score >= thresholds.get("critical", 8.0):
        level = "CRITICAL"
    elif risk_score >= thresholds.get("high", 5.0):
        level = "HIGH"
    elif risk_score >= thresholds.get("medium", 3.0):
        level = "MEDIUM"
    else:
        level = "NONE"

    # 规则引擎结果可以向上提升等级
    level_order = {"NONE": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    for rule in rules:
        rule_level = rule.get("severity", "NONE")
        if level_order.get(rule_level, 0) > level_order.get(level, 0):
            level = rule_level

    return level


# ============================================================
# 阶段6：内容分类
# ============================================================

def classify_content(
    text: str,
    kw_stats: dict,
    rules: list[dict],
    kb_matches: list[dict],
) -> dict:
    """
    对内容进行细分类。

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
# LLM调用模块（v3：prompt 输出 content_type 字段）
# ============================================================

import time as _time

def call_llm(
    prompt: str,
    system_prompt: str = "",
    config: Optional[dict] = None,
    max_retries: int = 3,
) -> Optional[str]:
    """
    调用智谱GLM（OpenAI兼容格式）。
    带重试和超时处理。失败时返回None，系统回退到纯规则引擎。
    """
    llm_config = (config or {}).get("llm", {})
    api_key = llm_config.get("api_key", "")
    endpoint = llm_config.get("endpoint", "")
    if not endpoint:
        api_base = llm_config.get("api_base", "")
        endpoint = f"{api_base.rstrip('/')}/chat/completions" if api_base else ""
    model = llm_config.get("model", "glm-4-flash")
    timeout = llm_config.get("timeout", 30)
    max_tokens = llm_config.get("max_tokens", 1024)
    temperature = llm_config.get("temperature", 0.1)
    enabled = llm_config.get("enabled", False)

    if not enabled:
        logger.debug("LLM未启用(enabled=false)，跳过")
        return None

    if not api_key or api_key == "YOUR_API_KEY_HERE" or not endpoint:
        logger.debug("LLM API Key或endpoint未配置，跳过LLM调用")
        return None

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

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if content:
                return content
            logger.warning(f"LLM返回空内容 (attempt {attempt})")
        except requests.Timeout:
            logger.warning(f"LLM调用超时 (attempt {attempt}/{max_retries})")
        except requests.RequestException as e:
            logger.warning(f"LLM调用失败 (attempt {attempt}/{max_retries}): {e}")
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.warning(f"LLM响应解析失败 (attempt {attempt}/{max_retries}): {e}")

        if attempt < max_retries:
            _time.sleep(1.0 * attempt)

    return None


def llm_analyze(
    text: str,
    rule_result: dict,
    config: Optional[dict] = None,
) -> Optional[dict]:
    """
    v3：对规则引擎判定为可疑的内容做LLM二次判断。
    返回 content_type 和 severity。

    返回：
        {
            "content_type": "PSEUDOSCIENCE|DEBUNKING|NORMAL_SCIENCE|NON_SCIENCE",
            "severity": "CRITICAL|HIGH|MEDIUM|NONE",
            "confidence": float,
            "category": str,
            "reasoning": str,
            "is_debunking": bool,
        }
    """
    system_prompt = """你是中国科协"科学辟谣"平台的资深内容审核专家，擅长识别伪科普、健康谣言、认知误区。

最重要的判断原则：先判断核心科学断言是否属实。
- 如果科学断言基本属实（如"黄曲霉毒素是强致癌物""发霉食物不能吃"），即使措辞有恐惧营销倾向（如"转给家人""杀不死"），也不算伪科普，应判定为 NORMAL_SCIENCE。
- 伪科普的本质是"科学断言错误或严重误导"，不是"语气夸张"。
- 典型伪科普：量子纠缠治病、食物相克致死、敲手臂排毒——核心断言就是假的。
- 不是伪科普：黄曲霉毒素致癌、隔夜菜亚硝酸盐风险——核心断言有科学依据，即使表述不够严谨。

你的核心能力：
1. 精准区分"传播谣言"和"辟谣文章"——辟谣文章会引用谣言内容来反驳，不能因为出现了谣言关键词就判定为伪科普
2. 识别常见的伪科普套路：恐惧营销、虚假权威、科学概念滥用、因果简化、绝对化表述
3. 判断科学断言的准确性

关于content_type的定义：
- PSEUDOSCIENCE：伪科普、谣言、认知误区——传播错误科学信息的内容
- DEBUNKING：辟谣内容——引用谣言是为了反驳/澄清，目的是消除误解
- NORMAL_SCIENCE：正常科普——传播正确科学知识的内容
- NON_SCIENCE：非科学内容——与科学/健康/食品无关

关于severity（仅当content_type为PSEUDOSCIENCE时有意义）：
- CRITICAL：确凿的伪科普/谣言，有明确的科学概念滥用或已被辟谣
- HIGH：明显的伪科普特征，高度可疑
- MEDIUM：有可疑迹象但也可能是表述不严谨
- NONE：不是伪科普（content_type非PSEUDOSCIENCE时必须为NONE）

关于confidence打分的严格校准规则：
- 0.9-1.0：你有确凿证据（如已知被辟谣的经典谣言、明确的科学概念滥用），绝对确定
- 0.7-0.9：有明显伪科普特征但不是100%确定
- 0.5-0.7：有可疑迹象但也可能是表述不严谨的正常讨论
- 0.3-0.5：不太确定，信号弱
- 0.0-0.3：几乎没有伪科普特征
注意：辟谣文章引用了谣言内容来反驳，confidence应该打低（0.1-0.3），因为它不是伪科普。不要因为出现了恐惧词就给高分——要看整体语境是在传播恐惧还是在消除恐惧。

请以严格JSON格式返回（不要markdown包裹）：
{
    "content_type": "PSEUDOSCIENCE/DEBUNKING/NORMAL_SCIENCE/NON_SCIENCE",
    "severity": "CRITICAL/HIGH/MEDIUM/NONE",
    "confidence": 0.0-1.0,
    "category": "伪科普/认知误区/冷饭热炒/新发谣言/辟谣内容/正常科普/正常内容",
    "reasoning": "一句话说明判断理由",
    "is_debunking": true/false
}"""

    # 截断过长文本（节省token）
    truncated = text[:800] if len(text) > 800 else text

    # 构造prompt，提供规则引擎的初步判断作为参考
    rules_desc = ""
    triggered = rule_result.get("triggered_rules", [])
    if triggered:
        rules_desc = "规则引擎触发：" + "、".join(
            [f"{r['rule_id']}({r['name']})" for r in triggered]
        )

    prompt = f"""请判断以下微博内容的类型和风险等级。

【微博内容】
{truncated}

【规则引擎参考】
当前风险评级：{rule_result.get('severity', '?')}，风险得分：{rule_result.get('risk_score', 0)}
{rules_desc}

请特别注意：
- 如果文章是在辟谣/澄清/科普，即使提到了谣言关键词，也应判断为DEBUNKING(is_debunking=true, severity=NONE)
- "量子纠缠治病""远程导引""能量疗愈"等属于典型PSEUDOSCIENCE
- 正规机构发布的科学常识普及属于NORMAL_SCIENCE(severity=NONE)
- content_type非PSEUDOSCIENCE时，severity必须为NONE

返回JSON："""

    response = call_llm(prompt, system_prompt, config)
    if not response:
        return None

    # 尝试解析JSON
    try:
        cleaned = response.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        result = json.loads(cleaned)
        # 确保必须字段存在
        result.setdefault("content_type", "PSEUDOSCIENCE")
        result.setdefault("severity", "MEDIUM")
        result.setdefault("confidence", 0.5)
        result.setdefault("category", "未知")
        result.setdefault("reasoning", "")
        result.setdefault("is_debunking", False)
        # 强制约束：非 PSEUDOSCIENCE 的 severity 必须为 NONE
        if result["content_type"] != "PSEUDOSCIENCE":
            result["severity"] = "NONE"
        return result
    except json.JSONDecodeError:
        logger.warning(f"LLM返回内容无法解析为JSON: {response[:200]}")
        return {
            "raw_response": response[:500],
            "content_type": "PSEUDOSCIENCE",
            "severity": "MEDIUM",
            "confidence": 0.0,
            "category": "解析失败",
            "reasoning": "LLM返回格式异常",
            "is_debunking": False,
        }


# ============================================================
# v3 主分析函数
# ============================================================

def analyze_text(
    text: str,
    config: Optional[dict] = None,
    kb: Optional[dict] = None,
    username: str = "",
    verified: bool = False,
    verified_type: int = -1,
) -> dict:
    """
    v3：对单条文本进行完整的伪科普分析。
    输出 content_type + severity 双层分类。

    参数：
        text: 待分析文本
        config: 系统配置
        kb: 谣言知识库（可选）
        username: 发帖用户名
        verified: 是否认证账号
        verified_type: 认证类型（0=个人, 1=企业, 2=团体, 3=媒体/政府, 7=其他）

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
        "is_debunking": False,
        "debunking_confidence": 0.0,
        "keyword_stats": {},
        "triggered_rules": [],
        "kb_matches": [],
        "risk_score": 0.0,
        # v3 核心输出
        "content_type": "NON_SCIENCE",
        "severity": "NONE",
        "rule_severity": "NONE",
        "classification": {},
        "llm_analysis": None,
        "llm_flipped": False,
        "llm_flip_direction": "",
        "requires_review": False,
    }

    # === 阶段1：预筛 ===
    is_science, science_kws = is_science_related(text)
    result["is_science_related"] = is_science
    result["science_keywords"] = science_kws

    if not is_science:
        logger.info("文本不涉科，跳过后续分析")
        result["content_type"] = "NON_SCIENCE"
        result["severity"] = "NONE"
        return result

    # === 阶段1.5：辟谣帖检测 ===
    is_debunk, debunk_conf = is_debunking_post(text, username)
    result["is_debunking"] = is_debunk
    result["debunking_confidence"] = debunk_conf

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

    # 认证媒体/机构/政府账号：风险得分衰减（降低误判倾向）
    if verified and verified_type in (2, 3):
        risk_score = round(risk_score * 0.7, 2)
        logger.debug(f"认证媒体/机构衰减: verified_type={verified_type}, 得分 ×0.7 → {risk_score}")

    severity = determine_rule_severity(risk_score, rules, config)

    # 辟谣帖降级保护
    if is_debunk and debunk_conf >= 0.5:
        level_order = {"NONE": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
        if level_order.get(severity, 0) >= 2:
            logger.info(f"辟谣帖保护：{severity} → MEDIUM (debunk_conf={debunk_conf})")
            severity = "MEDIUM"

    result["risk_score"] = risk_score
    result["rule_severity"] = severity

    # === 阶段6：分类 ===
    classification = classify_content(text, kw_stats, rules, kb_matches)
    result["classification"] = classification

    # === 阶段7：确定 content_type ===
    # 基于规则引擎 + 辟谣检测的初步 content_type 判定
    if is_debunk and debunk_conf >= 0.4:
        result["content_type"] = "DEBUNKING"
        result["severity"] = "NONE"
    elif severity in ("MEDIUM", "HIGH", "CRITICAL"):
        result["content_type"] = "PSEUDOSCIENCE"
        result["severity"] = severity
    else:
        # 规则引擎判为无风险的涉科内容 → 默认 NORMAL_SCIENCE
        result["content_type"] = "NORMAL_SCIENCE"
        result["severity"] = "NONE"

    # === 阶段8：LLM二次判断 ===
    # 只对规则引擎判定为可疑（PSEUDOSCIENCE）的内容调LLM
    # 另外：规则引擎判为DEBUNKING但置信度不高的也调LLM确认
    needs_llm = (
        result["content_type"] == "PSEUDOSCIENCE"
        or (result["content_type"] == "DEBUNKING" and debunk_conf < 0.7)
    )

    if needs_llm:
        llm_result = llm_analyze(text, result, config)
        result["llm_analysis"] = llm_result

        if llm_result and isinstance(llm_result, dict) and "content_type" in llm_result:
            llm_content_type = llm_result.get("content_type", result["content_type"])
            llm_severity = llm_result.get("severity", "NONE")
            llm_is_debunk = llm_result.get("is_debunking", False)
            llm_confidence = llm_result.get("confidence", 0.0)

            # 强制约束
            if llm_content_type != "PSEUDOSCIENCE":
                llm_severity = "NONE"

            old_ct = result["content_type"]
            old_sev = result["severity"]

            # LLM翻转逻辑
            if llm_confidence >= 0.6:
                if llm_content_type != old_ct:
                    result["content_type"] = llm_content_type
                    result["severity"] = llm_severity
                    result["llm_flipped"] = True

                    if old_ct == "PSEUDOSCIENCE" and llm_content_type in ("DEBUNKING", "NORMAL_SCIENCE"):
                        result["llm_flip_direction"] = "downgrade"
                        if llm_is_debunk:
                            result["is_debunking"] = True
                        logger.info(f"LLM翻转↓: {old_ct}/{old_sev} → {llm_content_type}/NONE (conf={llm_confidence})")
                    elif old_ct in ("DEBUNKING", "NORMAL_SCIENCE") and llm_content_type == "PSEUDOSCIENCE":
                        result["llm_flip_direction"] = "upgrade"
                        logger.info(f"LLM翻转↑: {old_ct} → PSEUDOSCIENCE/{llm_severity} (conf={llm_confidence})")
                    else:
                        result["llm_flip_direction"] = "reclassify"
                        logger.info(f"LLM重分类: {old_ct} → {llm_content_type} (conf={llm_confidence})")

                elif llm_content_type == "PSEUDOSCIENCE" and old_ct == "PSEUDOSCIENCE":
                    # 同为PSEUDOSCIENCE，LLM可调整severity
                    level_order = {"NONE": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
                    if level_order.get(llm_severity, 0) != level_order.get(old_sev, 0):
                        result["severity"] = llm_severity
                        if level_order.get(llm_severity, 0) > level_order.get(old_sev, 0):
                            result["llm_flipped"] = True
                            result["llm_flip_direction"] = "upgrade"
                        elif level_order.get(llm_severity, 0) < level_order.get(old_sev, 0):
                            result["llm_flipped"] = True
                            result["llm_flip_direction"] = "downgrade"

    # 需要人工审核的标记
    result["requires_review"] = (
        (result["content_type"] == "PSEUDOSCIENCE" and result["severity"] == "MEDIUM")
        or (result["content_type"] == "PSEUDOSCIENCE" and not rules)
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

            username = item.get("username", "")
            item_verified = item.get("verified", False)
            item_verified_type = item.get("verified_type", -1)
            logger.info(f"分析第 {line_num} 条: {text[:50]}...")
            analysis = analyze_text(
                text, config=config, kb=kb, username=username,
                verified=item_verified, verified_type=item_verified_type,
            )

            # 合并原始数据和分析结果
            output_item = {**item, "analysis": analysis}
            fout.write(json.dumps(output_item, ensure_ascii=False) + "\n")

            count += 1
            if analysis["content_type"] == "PSEUDOSCIENCE":
                flagged += 1

    logger.info(f"v3分析完成: 共 {count} 条")
    logger.info(f"  PSEUDOSCIENCE (伪科普): {flagged}")
    return count


# ============================================================
# 命令行入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="伪科普内容LLM识别分析工具 v3",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
    # 分析单条文本
    python analyzer_v3.py --text "量子能量水，100%有效，永久改善睡眠"

    # 批量分析JSONL文件
    python analyzer_v3.py --file data/weibo_real_2026-04-23.jsonl --output data/analysis_v3_2026-04-24.jsonl
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
        config = load_config(args.config)
        result = analyze_text(args.text, config=config)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.file:
        if not args.output:
            date_str = datetime.now().strftime("%Y-%m-%d")
            args.output = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "data",
                f"analysis_v3_{date_str}.jsonl",
            )
        count = analyze_file(args.file, args.output, config_path=args.config)
        print(f"\n✅ v3分析完成: {count} 条，输出到: {args.output}")


if __name__ == "__main__":
    main()
