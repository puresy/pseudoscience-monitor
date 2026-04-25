#!/usr/bin/env python3
"""
Playwright微博采集脚本 - 伪科普监测系统 MVP

使用Playwright加载已保存的微博Cookie，通过移动端API搜索并提取微博内容。
输出JSONL格式，与现有analyzer兼容。

用法：
    python weibo_playwright.py
    python weibo_playwright.py --output data/weibo_real_2026-04-23.jsonl
    python weibo_playwright.py --keywords "量子 养生" "致癌 食物"
"""

import argparse
import json
import logging
import os
import random
import re
import sys
import time
import urllib.parse
from datetime import datetime

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ============================================================
# 配置
# ============================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_COOKIE_PATH = os.path.join(SCRIPT_DIR, "weibo_cookies.json")
DEFAULT_OUTPUT_DIR = os.path.join(SCRIPT_DIR, "data")
DATE_STR = datetime.now().strftime("%Y-%m-%d")
DEFAULT_OUTPUT_FILE = os.path.join(DEFAULT_OUTPUT_DIR, f"weibo_real_{DATE_STR}.jsonl")

# 10个最容易命中伪科普的关键词
DEFAULT_KEYWORDS = [
    "致癌 食物",
    "量子 养生",
    "偏方 治病",
    "食物相克",
    "排毒 养颜",
    "5G 辐射",
    "酸碱体质",
    "保健品 治癌",
    "干细胞 抗衰",
    "疫苗 有害",
]

# 采集参数
DELAY_MIN = 3  # 每次搜索最小延时（秒）
DELAY_MAX = 8  # 每次搜索最大延时（秒）
PAGE_WAIT_MS = 6000  # 页面加载等待时间（毫秒）
MAX_RETRIES = 2  # 单个关键词最大重试次数

# 移动端API基础URL
MOBILE_SEARCH_URL = "https://m.weibo.cn/search"
MOBILE_API_URL = "https://m.weibo.cn/api/container/getIndex"

USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
)


# ============================================================
# Cookie处理
# ============================================================

def load_cookies(cookie_path: str) -> list[dict]:
    """加载并修正Cookie"""
    with open(cookie_path, "r", encoding="utf-8") as f:
        cookies = json.load(f)

    fixed = []
    for c in cookies:
        cc = dict(c)
        # 确保domain以点开头（通配匹配子域名）
        if cc.get("domain") and not cc["domain"].startswith("."):
            cc["domain"] = "." + cc["domain"]
        # 负数expires表示会话Cookie，移除expires字段
        if cc.get("expires", 0) < 0:
            cc.pop("expires", None)
        fixed.append(cc)

    return fixed


# ============================================================
# 粉丝数解析
# ============================================================

def parse_followers_count(val) -> int:
    """
    解析微博粉丝数字符串。
    "16.6万" -> 166000, "1446.4万" -> 14464000, 12345 -> 12345
    """
    if isinstance(val, (int, float)):
        return int(val)
    if not isinstance(val, str):
        return 0

    val = val.strip()
    multiplier = 1
    if val.endswith("万"):
        multiplier = 10000
        val = val[:-1]
    elif val.endswith("亿"):
        multiplier = 100000000
        val = val[:-1]

    try:
        return int(float(val) * multiplier)
    except (ValueError, TypeError):
        return 0


# ============================================================
# HTML标签清洗
# ============================================================

def clean_html(text: str) -> str:
    """清除HTML标签，只保留纯文本"""
    if not text:
        return ""
    # 移除所有HTML标签
    clean = re.sub(r"<[^>]+>", "", text)
    # 处理HTML实体
    clean = clean.replace("&amp;", "&")
    clean = clean.replace("&lt;", "<")
    clean = clean.replace("&gt;", ">")
    clean = clean.replace("&quot;", '"')
    clean = clean.replace("&nbsp;", " ")
    clean = clean.replace("&#39;", "'")
    # 清理多余空白
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


# ============================================================
# 时间解析
# ============================================================

def parse_weibo_time(created_at: str) -> str:
    """
    解析微博时间格式。
    "Wed Apr 22 20:32:14 +0800 2026" -> "2026-04-22 20:32:14"
    """
    if not created_at:
        return ""
    try:
        # 微博标准时间格式
        dt = datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        # 可能是相对时间："刚刚", "X分钟前", "X小时前", "昨天 HH:MM"
        return created_at


# ============================================================
# 从API响应中提取微博
# ============================================================

def extract_weibos_from_response(data: dict, keyword: str) -> list[dict]:
    """
    从移动端API响应中提取微博条目。

    返回与现有weibo_raw格式兼容的字典列表。
    """
    results = []
    cards = data.get("data", {}).get("cards", [])

    for card in cards:
        mblogs = []

        # card_type=9: 直接包含mblog
        if card.get("card_type") == 9 and card.get("mblog"):
            mblogs.append(card["mblog"])

        # card_type=11: 嵌套在card_group中
        if card.get("card_group"):
            for item in card["card_group"]:
                if isinstance(item, dict) and item.get("mblog"):
                    mblogs.append(item["mblog"])

        for mb in mblogs:
            user = mb.get("user") or {}
            weibo_id = str(mb.get("id", mb.get("mid", "")))

            # 清洗正文
            raw_text = mb.get("text", "")
            text = clean_html(raw_text)

            if not text:
                continue

            item = {
                "weibo_id": weibo_id,
                "username": user.get("screen_name", ""),
                "user_id": str(user.get("id", "")),
                "followers_count": parse_followers_count(user.get("followers_count", 0)),
                "verified": user.get("verified", False),
                "verified_type": user.get("verified_type", -1),
                "publish_time": parse_weibo_time(mb.get("created_at", "")),
                "text": text,
                "reposts_count": mb.get("reposts_count", 0),
                "comments_count": mb.get("comments_count", 0),
                "attitudes_count": mb.get("attitudes_count", 0),
                "source_url": f"https://m.weibo.cn/detail/{weibo_id}",
                "keyword": keyword,
                "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

            results.append(item)

    return results


# ============================================================
# 核心采集逻辑
# ============================================================

def crawl_keyword(page, keyword: str, max_pages: int = 2) -> list[dict]:
    """
    使用Playwright搜索单个关键词并提取结果。

    通过拦截移动端API响应获取结构化数据（比DOM解析更稳定）。

    参数：
        page: Playwright Page对象
        keyword: 搜索关键词
        max_pages: 最大采集页数（默认2页，约20条）

    返回：
        微博条目列表
    """
    all_results = []
    seen_ids = set()
    api_responses = []

    def capture_api_response(response):
        """拦截API响应"""
        if "api/container/getIndex" in response.url:
            try:
                data = response.json()
                api_responses.append(data)
            except Exception:
                pass

    page.on("response", capture_api_response)

    try:
        for page_num in range(1, max_pages + 1):
            api_responses.clear()

            if page_num == 1:
                # 第一页：访问搜索页面触发API调用
                q = urllib.parse.quote(keyword)
                url = f"{MOBILE_SEARCH_URL}?containerid=100103type%3D1%26q%3D{q}"
                logger.info(f"  搜索第{page_num}页: {keyword}")

                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                except PlaywrightTimeout:
                    logger.warning(f"  页面加载超时: {keyword}")
                    break

                page.wait_for_timeout(PAGE_WAIT_MS)
            else:
                # 后续页面：通过滚动触发加载，或直接调用API
                logger.info(f"  加载第{page_num}页...")

                # 滚动到底部触发分页加载
                for _ in range(3):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(2000)

            # 检查是否被重定向到登录页
            current_url = page.url
            if "passport" in current_url or "login" in current_url:
                logger.error("  ⚠ Cookie失效，被重定向到登录页！")
                return all_results

            # 检查是否有验证码
            content = page.content()
            if "verify" in content.lower() and "captcha" in content.lower():
                logger.error("  ⚠ 遭遇验证码，停止采集！")
                return all_results

            # 从捕获的API响应中提取数据
            for resp_data in api_responses:
                weibos = extract_weibos_from_response(resp_data, keyword)
                for wb in weibos:
                    if wb["weibo_id"] not in seen_ids:
                        seen_ids.add(wb["weibo_id"])
                        all_results.append(wb)

            # 如果没有捕获到API响应（可能第一次加载用的缓存），
            # 尝试通过page.evaluate直接调用API
            if not api_responses and page_num == 1:
                logger.info("  未捕获API响应，尝试直接调用API...")
                q = urllib.parse.quote(keyword)
                container_id = f"100103type=1&q={keyword}"
                api_url = (
                    f"{MOBILE_API_URL}?"
                    f"containerid={urllib.parse.quote(container_id)}"
                    f"&page_type=searchall"
                )
                try:
                    resp = page.evaluate(
                        f"""async () => {{
                            const r = await fetch("{api_url}");
                            return await r.json();
                        }}"""
                    )
                    if isinstance(resp, dict) and resp.get("ok") == 1:
                        weibos = extract_weibos_from_response(resp, keyword)
                        for wb in weibos:
                            if wb["weibo_id"] not in seen_ids:
                                seen_ids.add(wb["weibo_id"])
                                all_results.append(wb)
                except Exception as e:
                    logger.warning(f"  直接API调用失败: {e}")

            logger.info(f"  当前共采集 {len(all_results)} 条")

            # 页间延时
            if page_num < max_pages:
                delay = random.uniform(1, 3)
                time.sleep(delay)

    finally:
        page.remove_listener("response", capture_api_response)

    return all_results


def run_crawl(
    cookie_path: str,
    keywords: list[str],
    output_file: str,
    max_pages_per_keyword: int = 2,
) -> dict:
    """
    主采集流程。

    参数：
        cookie_path: Cookie文件路径
        keywords: 关键词列表
        output_file: 输出JSONL文件路径
        max_pages_per_keyword: 每个关键词最大采集页数

    返回：
        采集统计信息
    """
    logger.info("=" * 60)
    logger.info("微博Playwright采集器启动")
    logger.info(f"关键词数量: {len(keywords)}")
    logger.info(f"输出文件: {output_file}")
    logger.info("=" * 60)

    # 加载Cookie
    cookies = load_cookies(cookie_path)
    logger.info(f"加载了 {len(cookies)} 条Cookie")

    # 统计
    stats = {
        "total": 0,
        "per_keyword": {},
        "errors": [],
        "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "login_expired": False,
        "captcha_hit": False,
    }

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    all_weibos = []
    global_seen_ids = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT)
        context.add_cookies(cookies)
        page = context.new_page()

        for i, keyword in enumerate(keywords):
            logger.info(f"\n[{i+1}/{len(keywords)}] 关键词: {keyword}")

            retries = 0
            results = []

            while retries <= MAX_RETRIES:
                try:
                    results = crawl_keyword(page, keyword, max_pages=max_pages_per_keyword)
                    break
                except Exception as e:
                    retries += 1
                    logger.warning(f"  采集失败 (重试 {retries}/{MAX_RETRIES}): {e}")
                    if retries > MAX_RETRIES:
                        stats["errors"].append(f"{keyword}: {str(e)}")
                    else:
                        time.sleep(2)

            # 检查登录状态
            if "passport" in page.url or "login" in page.url:
                logger.error("Cookie已失效，停止采集")
                stats["login_expired"] = True
                stats["errors"].append(f"Cookie失效，在关键词'{keyword}'处停止")
                break

            # 去重并记录
            new_count = 0
            for wb in results:
                if wb["weibo_id"] not in global_seen_ids:
                    global_seen_ids.add(wb["weibo_id"])
                    all_weibos.append(wb)
                    new_count += 1

            stats["per_keyword"][keyword] = new_count
            logger.info(f"  → 新增 {new_count} 条（去重后）")

            # 关键词间延时
            if i < len(keywords) - 1:
                delay = random.uniform(DELAY_MIN, DELAY_MAX)
                logger.info(f"  等待 {delay:.1f} 秒...")
                time.sleep(delay)

        browser.close()

    # 写入JSONL
    with open(output_file, "w", encoding="utf-8") as f:
        for wb in all_weibos:
            f.write(json.dumps(wb, ensure_ascii=False) + "\n")

    stats["total"] = len(all_weibos)
    stats["end_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    logger.info("\n" + "=" * 60)
    logger.info(f"采集完成: 共 {stats['total']} 条微博")
    logger.info(f"输出文件: {output_file}")
    for kw, cnt in stats["per_keyword"].items():
        logger.info(f"  {kw}: {cnt} 条")
    if stats["errors"]:
        logger.warning(f"错误: {stats['errors']}")
    logger.info("=" * 60)

    # 保存统计信息
    stats_file = output_file.replace(".jsonl", "_stats.json")
    with open(stats_file, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    logger.info(f"统计信息: {stats_file}")

    return stats


# ============================================================
# CLI入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Playwright微博采集脚本 - 伪科普监测系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--cookies",
        default=DEFAULT_COOKIE_PATH,
        help=f"Cookie文件路径（默认: {DEFAULT_COOKIE_PATH}）",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_FILE,
        help=f"输出JSONL文件路径（默认: {DEFAULT_OUTPUT_FILE}）",
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        default=None,
        help="自定义关键词列表（默认使用内置列表）",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=2,
        help="每个关键词最大采集页数（默认: 2）",
    )

    args = parser.parse_args()

    if not os.path.exists(args.cookies):
        logger.error(f"Cookie文件不存在: {args.cookies}")
        sys.exit(1)

    keywords = args.keywords or DEFAULT_KEYWORDS

    stats = run_crawl(
        cookie_path=args.cookies,
        keywords=keywords,
        output_file=args.output,
        max_pages_per_keyword=args.max_pages,
    )

    if stats["login_expired"]:
        logger.error("\n⚠ Cookie已过期，请重新登录微博并导出Cookie。")
        sys.exit(2)

    if stats["total"] == 0:
        logger.warning("\n⚠ 未采集到任何数据，请检查Cookie和网络。")
        sys.exit(3)

    print(f"\n✅ 采集完成: {stats['total']} 条微博 → {args.output}")


if __name__ == "__main__":
    main()
