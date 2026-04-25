# 伪科普监测系统 — Pipeline 数据规格文档

> 版本：v1.0 · 日期：2026-04-24 · 状态：草案

---

## 目录

1. [数据采集规格](#1-数据采集规格)
2. [原始数据字段定义](#2-原始数据字段定义)
3. [分类引擎规格](#3-分类引擎规格)
4. [分析结果字段定义](#4-分析结果字段定义)
5. [增量采集逻辑](#5-增量采集逻辑)
6. [文件命名规范](#6-文件命名规范)
7. [看板数据规格](#7-看板数据规格)

---

## 1. 数据采集规格

### 1.1 数据源

微博搜索 API（Playwright 采集），通过移动端 `m.weibo.cn` 接口拦截结构化 JSON 响应。

- 实现文件：`weibo_playwright.py`
- API 端点：`https://m.weibo.cn/api/container/getIndex`
- 采集方式：Playwright 加载已保存的微博 Cookie，拦截 `response` 事件获取 API 返回数据

### 1.2 搜索关键词列表

当前 10 个种子关键词（定义在 `weibo_playwright.py` 的 `DEFAULT_KEYWORDS` 中）：

| # | 关键词 | 目标场景 |
|---|--------|----------|
| 1 | `致癌 食物` | 食品致癌谣言 |
| 2 | `量子 养生` | 科学概念滥用 |
| 3 | `偏方 治病` | 虚假疗法 |
| 4 | `食物相克` | 食品安全谣言 |
| 5 | `排毒 养颜` | 伪养生 |
| 6 | `5G 辐射` | 辐射恐惧 |
| 7 | `酸碱体质` | 经典谣言 |
| 8 | `保健品 治癌` | 虚假宣传 |
| 9 | `干细胞 抗衰` | 科学概念滥用 |
| 10 | `疫苗 有害` | 反疫苗谣言 |

> **注意**：`keywords.txt` 中有更多关键词（约 50+ 条），用于规则引擎种子库，但 Playwright 采集默认只使用上述 10 个。两者不要混淆。

### 1.3 时间窗口

采集时需要指定时间范围，格式 `YYYY-MM-DD ~ YYYY-MM-DD`。

> **TODO: 需修改代码** — 当前 `weibo_playwright.py` 没有时间窗口过滤参数。搜索 URL 使用综合排序（`type=1`），未指定 `timescope` 参数。导致采集到的 435 条数据跨 2017–2026 年。
>
> 需要修改：
> 1. `crawl_keyword()` 增加 `start_date` / `end_date` 参数
> 2. 搜索 containerid 追加 `&timescope=custom:YYYY-MM-DD-0:YYYY-MM-DD-23` 限定时间范围
> 3. 或在 API 请求 URL 中拼接 `&starttime=` / `&endtime=` 参数

### 1.4 排序方式

**应使用按时间排序**（`type=61` 或 `typeall=1&xsort=time`），不使用综合排序。

> **TODO: 需修改代码** — 当前搜索 URL 使用 `type%3D1`（综合排序）。需要改为时间排序参数。微博移动端搜索时间排序的 containerid 格式为：
> ```
> 100103type=61&q={keyword}&t=0
> ```
> 或在 URL 中追加 `&xsort=time`。

### 1.5 采集频率

- 常规频率：**每周一次**
- 时间窗口：上周五 00:00 → 本周五 00:00（7 天）
- 触发方式：手动运行（MVP 阶段不做自动调度）

### 1.6 去重逻辑

- 采集阶段：按 `weibo_id` 去重（`weibo_playwright.py` 的 `global_seen_ids` 已实现）
- 跨批次去重：合并时按 `weibo_id` 去重，保留最新分析结果

### 1.7 采集参数

| 参数 | 值 | 来源 |
|------|-----|------|
| 每关键词最大页数 | 2 页（约 20 条） | `weibo_playwright.py` 默认 |
| 关键词间延时 | 3–8 秒随机 | `DELAY_MIN` / `DELAY_MAX` |
| 页面加载等待 | 6000 ms | `PAGE_WAIT_MS` |
| 单关键词最大重试 | 2 次 | `MAX_RETRIES` |

### 1.8 原始数据文件命名

```
data/weibo_raw_{start}_{end}.jsonl
```

其中 `{start}` 和 `{end}` 为采集窗口的起止日期（`YYYY-MM-DD` 格式）。

> **TODO: 需修改代码** — 当前文件命名为 `weibo_real_{date}.jsonl`（单日期），不包含时间窗口信息。需要改为 `weibo_raw_{start}_{end}.jsonl` 格式。

---

## 2. 原始数据字段定义

每条微博的标准字段（来源：`weibo_playwright.py` → `extract_weibos_from_response()`）：

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `weibo_id` | `str` | 微博唯一 ID | `"5151798406846592"` |
| `username` | `str` | 用户昵称 | `"营养师王丽玲"` |
| `user_id` | `str` | 用户 ID | `"1234567890"` |
| `followers_count` | `int` | 粉丝数（已解析，如 "16.6万" → 166000） | `166000` |
| `verified` | `bool` | 是否认证 | `true` |
| `verified_type` | `int` | 认证类型 | `0` |
| `publish_time` | `str` | 发布时间 `"YYYY-MM-DD HH:MM:SS"` | `"2026-04-22 20:32:14"` |
| `text` | `str` | 微博全文（HTML 标签已清洗） | `"10种黄曲霉素的重灾食物..."` |
| `reposts_count` | `int` | 转发数 | `58` |
| `comments_count` | `int` | 评论数 | `123` |
| `attitudes_count` | `int` | 点赞数 | `456` |
| `source_url` | `str` | 原文链接 | `"https://m.weibo.cn/detail/5151798406846592"` |
| `keyword` | `str` | 命中的搜索关键词 | `"致癌 食物"` |
| `crawl_time` | `str` | 采集时间 `"YYYY-MM-DD HH:MM:SS"` | `"2026-04-23 14:30:00"` |

### 认证类型编码

| `verified_type` | 含义 |
|---|---|
| -1 | 未认证 |
| 0 | 个人认证（黄 V） |
| 1 | 企业认证 |
| 2 | 团体/机构认证 |
| 3 | 媒体/政府认证（蓝 V） |
| 7 | 其他认证 |

> **注**：代码中 `verified_type` 取自微博 API 返回的 `user.verified_type` 字段。当 `verified=false` 时，`verified_type` 通常为 `-1`。

---

## 3. 分类引擎规格

实现文件：`analyzer_v3.py`

### 3.1 内容分类（content_type）

| 值 | 定义 | 判定条件 |
|---|---|---|
| `PSEUDOSCIENCE` | 伪科普/谣言 | 核心科学断言错误或严重误导 |
| `DEBUNKING` | 辟谣内容 | 主动揭露/反驳伪科普的内容 |
| `NORMAL_SCIENCE` | 正常科普 | 核心科学断言基本属实 |
| `NON_SCIENCE` | 非科学内容 | 娱乐/段子/广告/新闻/无关内容 |

### 3.2 风险等级（severity）

仅 `PSEUDOSCIENCE` 使用 `CRITICAL` / `HIGH` / `MEDIUM`，其余一律 `NONE`：

| 值 | 条件 | 代码阈值 |
|---|---|---|
| `CRITICAL` | 直接危害生命安全（如"放弃化疗用偏方"） | `risk_score >= 8.0` 或规则 R1/R2/R3 的 CRITICAL 触发 |
| `HIGH` | 可能造成健康损害或经济损失 | `risk_score >= 5.0` |
| `MEDIUM` | 认知误导但不直接危害 | `risk_score >= 3.0` |
| `NONE` | 非 PSEUDOSCIENCE 一律为 NONE | `risk_score < 3.0` 或非伪科普 |

> 阈值定义在 `config.yaml` → `analyzer.risk_thresholds`。

### 3.3 判定流程

```
原始微博
  │
  ├─ 阶段1: 预筛（涉科关键词命中 ≥1）
  │   ├─ 不涉科 → NON_SCIENCE / NONE → 输出，不调LLM
  │   └─ 涉科 → 继续
  │
  ├─ 阶段1.5: 辟谣帖检测
  │   ├─ 辟谣置信度 ≥0.4 → 标记 is_debunking=true
  │   └─ 辟谣置信度 <0.4 → 继续
  │
  ├─ 阶段2: 关键词密度分析（9类关键词统计）
  │
  ├─ 阶段3: 规则引擎（6条组合规则 R1~R6）
  │
  ├─ 阶段4: 事实核查（谣言知识库比对）
  │
  ├─ 阶段5: 风险评分（加权 0-10 分）
  │   └─ 认证媒体/机构衰减：verified_type ∈ {2,3} → 得分 ×0.7
  │
  ├─ 阶段6: 初步 content_type 判定
  │   ├─ 辟谣帖(置信度≥0.4) → DEBUNKING / NONE
  │   ├─ severity ∈ {MEDIUM, HIGH, CRITICAL} → PSEUDOSCIENCE / {severity}
  │   └─ 其他涉科内容 → NORMAL_SCIENCE / NONE
  │
  └─ 阶段7: LLM 二次判断（仅对以下情况调用）
      ├─ content_type == PSEUDOSCIENCE → 调LLM确认
      ├─ content_type == DEBUNKING 且置信度 <0.7 → 调LLM确认
      └─ LLM置信度 ≥0.6 时可翻转 content_type
```

### 3.4 规则引擎详情

6 条组合规则（`apply_rules()` 函数）：

| 规则 ID | 名称 | 触发条件 | 默认 severity |
|---------|------|----------|---------------|
| R1 | 恐惧营销模式 | 恐惧词 ≥1 + 紧迫感 ≥1（有/无营销词分两级） | CRITICAL/HIGH（有科学引用时降至 HIGH/MEDIUM） |
| R2 | 权威虚构 | 虚假权威 ≥1（+见证堆砌时升级） | MEDIUM → HIGH → CRITICAL |
| R3 | 科学滥用+功效夸大 | 科学滥用 ≥1 + 夸大效能 ≥1 | HIGH/CRITICAL |
| R4 | 因果简化+绝对化 | 绝对化词 ≥1 + 疾病关联 | HIGH |
| R5 | 食品相克谣言 | 食品相克触发词 ≥1 | MEDIUM |
| R6 | 营销导向内容 | 营销词 ≥2 | HIGH |

### 3.5 风险评分公式

```
score = 0

# 关键词维度（各维度 0-10 分，按权重加总）
score += min(fear_count × 2.5, 10) × weight_fear        # 权重 0.30
score += min(urgency_count × 3.0, 10) × 0.20
score += min(absolute_count × 3.0, 10) × weight_absolute  # 权重 0.25
score += min(authority_count × 3.5, 10) × weight_authority # 权重 0.25
score += min(marketing_count × 3.0, 10) × weight_product   # 权重 0.20
score += min(testimony_count × 3.0, 10) × weight_testimony # 权重 0.15

# 加分项
score += min(science_abuse_count × 2.0, 3)
score += min(exaggeration_count × 1.5, 3)

# 规则触发加分
for rule in triggered_rules:
    if rule.severity == CRITICAL:  score += 4.0
    if rule.severity == HIGH:      score += 2.5
    if rule.severity == MEDIUM:    score += 1.0

# 知识库匹配加分
if kb_matches:
    score += best_overlap_ratio × 4.0

# 认证衰减
if verified and verified_type in (2, 3):
    score *= 0.7

score = min(score, 10.0)
```

> 权重定义在 `config.yaml` → `analyzer.weights`。

### 3.6 核心判定原则（优先级从高到低）

1. **科学断言真假优先**：先判断核心科学断言是否属实，属实则不是伪科普。如"黄曲霉毒素致癌"是科学事实，即使用了恐惧营销措辞也不算 PSEUDOSCIENCE。
2. **按传播效果判**：不管发帖者意图（反讽/钓鱼），读者会怎么理解就怎么分类。
3. **立场判断**：区分"传播谣言"和"质疑/反驳谣言"。辟谣帖引用谣言是为了反驳，不能因为出现谣言关键词就判定为伪科普。
4. **新闻报道豁免**：报道假药被查处、谣言被辟谣的新闻 → `DEBUNKING`。
5. **认证媒体衰减**：认证媒体/机构账号（`verified_type` ∈ {2, 3}）的规则触发风险得分 ×0.7。

> 原则 1–4 主要通过 LLM system prompt 和辟谣帖检测实现。原则 5 在代码 `analyze_text()` 中硬编码。

### 3.7 LLM 二次判断

- 模型：`glm-4-flash`（智谱清言）
- 触发条件：规则引擎判为 PSEUDOSCIENCE，或 DEBUNKING 但置信度 <0.7
- LLM 返回字段：`content_type`, `severity`, `confidence`, `category`, `reasoning`, `is_debunking`
- 翻转阈值：LLM `confidence >= 0.6` 时可翻转规则引擎的判定
- 不调 LLM 的场景：NON_SCIENCE（预筛阶段直接输出）、NORMAL_SCIENCE（规则引擎无触发）

### 3.8 已知 LLM 盲区

- **科学事实判断不准**：GLM-4-flash 对"黄曲霉毒素耐高温"等具体科学细节判断不一致，不同 prompt 下结论可能矛盾。
- **辟谣帖误判**：部分辟谣帖引用了大量谣言原文来反驳，LLM 可能被引用内容干扰而判定为 PSEUDOSCIENCE。
- **反讽/讽刺识别弱**：讽刺语气的微博可能被当作正经传播。

> **后续改进方向**：
> - 科学事实白名单（常见科学断言 → 已知真/假的查找表）
> - 换更强模型（GLM-4-plus 或 DeepSeek）
> - LLM 多轮投票（同一条微博调 2–3 次取多数）

---

## 4. 分析结果字段定义

每条分析结果是原始微博字段 + `analysis` 嵌套对象。输出文件为 JSONL 格式，每行一个 JSON 对象。

### 4.1 顶层字段（继承自原始数据）

| 字段 | 类型 | 说明 |
|------|------|------|
| `weibo_id` | `str` | 微博唯一 ID |
| `username` | `str` | 用户昵称 |
| `user_id` | `str` | 用户 ID |
| `followers_count` | `int` | 粉丝数 |
| `verified` | `bool` | 是否认证 |
| `verified_type` | `int` | 认证类型 |
| `publish_time` | `str` | 发布时间 |
| `text` | `str` | 微博全文 |
| `reposts_count` | `int` | 转发数 |
| `comments_count` | `int` | 评论数 |
| `attitudes_count` | `int` | 点赞数 |
| `source_url` | `str` | 原文链接 |
| `keyword` | `str` | 命中的搜索关键词 |
| `crawl_time` | `str` | 采集时间 |

### 4.2 analysis 嵌套对象

| 字段 | 类型 | 说明 |
|------|------|------|
| `text` | `str` | 原文截断（≤200 字 + `"..."`） |
| `text_length` | `int` | 原文长度 |
| `analysis_time` | `str` | 分析执行时间 |
| `is_science_related` | `bool` | 是否涉科 |
| `science_keywords` | `list[str]` | 命中的科学领域关键词 |
| `is_debunking` | `bool` | 是否辟谣帖 |
| `debunking_confidence` | `float` | 辟谣置信度 (0–1) |
| `keyword_stats` | `dict` | 9 类关键词命中统计（见 §4.3） |
| `triggered_rules` | `list[dict]` | 触发的规则列表（见 §4.4） |
| `kb_matches` | `list[dict]` | 知识库匹配结果 |
| `risk_score` | `float` | 风险评分 (0–10) |
| `content_type` | `str` | 最终内容分类：`PSEUDOSCIENCE` \| `DEBUNKING` \| `NORMAL_SCIENCE` \| `NON_SCIENCE` |
| `severity` | `str` | 最终风险等级：`CRITICAL` \| `HIGH` \| `MEDIUM` \| `NONE` |
| `rule_severity` | `str` | 规则引擎的初步判定（LLM 翻转前） |
| `classification` | `dict` | 内容细分类：`{category, category_cn, subtype, subtype_cn, reason}` |
| `llm_analysis` | `dict \| null` | LLM 返回结果（未调用时为 `null`） |
| `llm_flipped` | `bool` | LLM 是否翻转了规则引擎的判定 |
| `llm_flip_direction` | `str` | 翻转方向：`""` / `"upgrade"` / `"downgrade"` / `"reclassify"` |
| `requires_review` | `bool` | 是否需要人工审核 |

### 4.3 keyword_stats 结构

9 个维度，每个维度结构相同：

```json
{
  "fear": {"count": 2, "hits": ["致癌", "有毒"], "density": 1.23},
  "urgency": {"count": 0, "hits": [], "density": 0.0},
  "absolute": {"count": 1, "hits": ["100%"], "density": 0.62},
  "fake_authority": {"count": 0, "hits": [], "density": 0.0},
  "fake_testimony": {"count": 0, "hits": [], "density": 0.0},
  "science_abuse": {"count": 0, "hits": [], "density": 0.0},
  "exaggeration": {"count": 0, "hits": [], "density": 0.0},
  "marketing": {"count": 0, "hits": [], "density": 0.0},
  "food_clash": {"count": 0, "hits": [], "density": 0.0}
}
```

### 4.4 triggered_rules 结构

```json
[
  {
    "rule_id": "R1",
    "name": "恐惧营销模式",
    "severity": "HIGH",
    "confidence": 0.80,
    "detail": "恐惧词(2个) + 紧迫感"
  }
]
```

> **注**：规则字段中没有 `matched_keywords`。如需此字段需修改 `apply_rules()` 返回值。

### 4.5 llm_analysis 结构（调用时）

```json
{
  "content_type": "PSEUDOSCIENCE",
  "severity": "HIGH",
  "confidence": 0.85,
  "category": "伪科普",
  "reasoning": "滥用量子概念进行虚假营销",
  "is_debunking": false
}
```

### 4.6 看板展平字段

`dashboard.html` 和 `detail.html` 使用展平后的数据。当前实现为：HTML 生成时将分析结果展平嵌入 `const DATA = [...]`。展平规则：

| 看板字段 | 来源 | 换算 |
|----------|------|------|
| `content_type` | `analysis.content_type` | 直接取 |
| `severity` | `analysis.severity` | 直接取 |
| `risk_score` | `analysis.risk_score` | 直接取 |
| `spread_score` | 计算 | `reposts_count + comments_count + attitudes_count` |
| `triggered_rules` | `analysis.triggered_rules` | 直接取数组 |
| `llm_analysis` | `analysis.llm_analysis` | 直接取（可为 null） |
| `llm_flipped` | `analysis.llm_flipped` | 直接取 |
| `llm_flip_direction` | `analysis.llm_flip_direction` | 直接取 |
| `is_debunking` | `analysis.is_debunking` | 直接取 |
| `keyword_stats` | `analysis.keyword_stats` | 直接取 |

> **TODO: 需修改代码** — 当前 `spread_score` 没有作为独立字段存储在分析结果中，而是在前端 JS 中实时计算（`detail.html` 第 378 行）。建议在分析阶段直接计算并写入。

---

## 5. 增量采集逻辑

### 5.1 采集输出

每次采集指定时间窗口，输出独立文件：

```
data/weibo_raw_{start}_{end}.jsonl      # 原始采集数据
```

示例：`data/weibo_raw_2026-04-18_2026-04-25.jsonl`

### 5.2 分析输出

分析结果按采集批次输出：

```
data/analysis_{start}_{end}.jsonl       # 分析结果（对应采集批次）
```

### 5.3 合并去重

所有批次的分析结果合并为主数据文件：

```
data/analysis_latest.jsonl              # 合并去重后的最新全量
```

合并规则：

1. 按 `weibo_id` 去重
2. 同一 `weibo_id` 出现在多个批次时，保留 **最新分析时间**（`analysis.analysis_time` 最大）的版本
3. 合并操作每次分析完成后自动触发

> **TODO: 需修改代码** — 当前系统没有合并逻辑。`run_pipeline.py` 每次运行输出独立的 `analysis_{date}.jsonl`，没有生成 `analysis_latest.jsonl`。需要新增合并脚本或在 pipeline 尾部追加合并步骤。

### 5.4 看板数据源

`dashboard.html` 和 `detail.html` 从 `analysis_latest.jsonl` 读取数据。

> **TODO: 需修改代码** — 当前看板数据是生成时硬编码嵌入 HTML 的（`const DATA = [...]`），不是运行时从文件加载。需要改为以下方案之一：
> - **方案 A**：每次合并后重新生成 HTML（保持当前嵌入模式，但数据源改为 `analysis_latest.jsonl`）
> - **方案 B**：HTML 改为运行时 `fetch('data/analysis_latest.jsonl')` 动态加载
>
> MVP 阶段推荐方案 A（简单可靠，不需要 HTTP 服务器）。

### 5.5 辟谣知识库更新

辟谣文章库独立于微博采集周期更新：

```
data/piyao_articles_{date}.jsonl        # 当次抓取的辟谣文章
data/rumor_knowledge_base.json          # 累计知识库（供分析引擎比对）
```

---

## 6. 文件命名规范

```
mvp/
├── docs/
│   └── pipeline_spec.md                 # 本文档
├── data/
│   ├── weibo_raw_{start}_{end}.jsonl    # 原始采集（按时间窗口）
│   ├── piyao_articles_{date}.jsonl      # 辟谣文章库（按日期）
│   ├── analysis_{start}_{end}.jsonl     # 分析结果（按采集批次）
│   ├── analysis_latest.jsonl            # 合并去重后的最新全量
│   ├── rumor_knowledge_base.json        # 谣言知识库（累计）
│   ├── pseudoscience_audit.md           # 人工审计报告
│   └── pseudoscience_audit.json         # 人工审计数据（结构化）
├── weibo_playwright.py                  # 采集脚本
├── analyzer_v3.py                       # 分类引擎
├── run_pipeline.py                      # 整合管道
├── piyao_crawler.py                     # 辟谣网站爬虫
├── config.yaml                          # 系统配置
├── keywords.txt                         # 关键词种子库
├── dashboard.html                       # 看板总览
└── detail.html                          # 看板明细
```

### 命名规则

| 模式 | 说明 | 示例 |
|------|------|------|
| `{start}_{end}` | 采集时间窗口，`YYYY-MM-DD` 格式 | `2026-04-18_2026-04-25` |
| `{date}` | 单日日期，`YYYY-MM-DD` 格式 | `2026-04-23` |
| `_latest` | 合并去重后的最新全量 | `analysis_latest.jsonl` |

### 现有文件兼容

当前 `data/` 下已有的旧命名文件：

| 现有文件 | 新规范文件 | 说明 |
|----------|-----------|------|
| `weibo_real_2026-04-23.jsonl` | `weibo_raw_{start}_{end}.jsonl` | TODO: 需重命名 |
| `weibo_raw_2026-04-23.jsonl` | `weibo_raw_{start}_{end}.jsonl` | TODO: 需重命名 |
| `analysis_2026-04-23.jsonl` | `analysis_{start}_{end}.jsonl` | TODO: 需重命名 |
| `analysis_v2_2026-04-23.jsonl` | — | 旧版本，可归档 |
| `analysis_v3_2026-04-24.jsonl` | `analysis_{start}_{end}.jsonl` | TODO: 需重命名 |
| `analysis_real_2026-04-23.jsonl` | — | 旧版本，可归档 |
| （不存在） | `analysis_latest.jsonl` | TODO: 需新增合并逻辑 |

---

## 7. 看板数据规格

### 7.1 数据来源

`dashboard.html` 和 `detail.html` 的数据来源为 `analysis_latest.jsonl`（或当前嵌入的 `const DATA` 数组）。

### 7.2 看板所需字段

以下字段是看板 JS 代码直接读取的（来源：`detail.html` 中的渲染函数分析）：

**主表格列（detail.html `renderRow()`）：**

| 字段 | 用途 | 必须 |
|------|------|------|
| `username` | 显示用户名 | ✅ |
| `text` | 显示微博内容（截断） | ✅ |
| `publish_time` | 显示发布时间 | ✅ |
| `content_type` | 类型标签颜色+文案 | ✅ |
| `severity` | 风险等级标签 | ✅ |
| `risk_score` | 风险分数显示+颜色 | ✅ |
| `reposts_count` | 传播量计算 | ✅ |
| `comments_count` | 传播量计算 | ✅ |
| `attitudes_count` | 传播量计算 | ✅ |
| `triggered_rules` | 规则显示 | ✅ |
| `llm_analysis` | LLM 标签显示 | ✅ |
| `llm_flipped` | 翻转标记 | ✅ |
| `llm_flip_direction` | 翻转方向 | ✅ |

**详情面板（detail.html `renderDetail()`）：**

| 字段 | 用途 |
|------|------|
| `source_url` | 原文链接 |
| `followers_count` | 粉丝数 |
| `verified` | 认证状态 |
| `keyword_stats` | 各维度关键词命中 |
| `is_debunking` | 辟谣帖标记 |
| `classification` | 细分类信息 |

**统计面板（detail.html `initStats()`）：**

| 计算 | 逻辑 |
|------|------|
| 各 content_type 计数 | `DATA.forEach(d => counts[d.content_type]++)` |
| 占比 | `count / DATA.length` |

### 7.3 看板展平规则

当前实现中，`const DATA` 数组的每个元素是展平后的结构——原始微博字段和 `analysis` 子对象的字段在同一层级：

```javascript
{
  // 原始字段
  "idx": 1,
  "username": "...",
  "text": "...",
  "publish_time": "...",
  "reposts_count": 58,
  "comments_count": 123,
  "attitudes_count": 456,
  "source_url": "...",
  "followers_count": 166000,
  "verified": true,
  "keyword": "致癌 食物",
  // 来自 analysis 的展平字段
  "content_type": "PSEUDOSCIENCE",
  "severity": "HIGH",
  "risk_score": 6.5,
  "triggered_rules": [...],
  "llm_analysis": {...},
  "llm_flipped": false,
  "llm_flip_direction": "",
  "is_debunking": false,
  "keyword_stats": {...},
  "classification": {...}
}
```

> **重要**：分析结果 JSONL 中 analysis 是嵌套的 `{"weibo_id":..., "analysis":{...}}`，但看板需要的是展平格式。生成看板 HTML 时需要做展平操作。

### 7.4 增量更新一致性保证

为确保增量采集不破坏看板一致性，需要遵守以下规则：

1. **单一数据源原则**：看板只从 `analysis_latest.jsonl` 读数据，不直接读某个批次文件
2. **合并后重新生成**：每次合并完成后重新生成看板 HTML（方案 A）
3. **字段向前兼容**：新增字段不影响旧数据展示（JS 中用 `d.field || default` 保护）
4. **weibo_id 唯一约束**：`analysis_latest.jsonl` 中每个 `weibo_id` 只出现一次

---

## 附录 A：现有代码与规格的差异清单

| # | 差异项 | 现状 | 规格要求 | 修改位置 |
|---|--------|------|----------|----------|
| 1 | 时间窗口 | 无时间过滤，综合排序 | 指定时间窗口 + 按时间排序 | `weibo_playwright.py` |
| 2 | 排序方式 | `type=1`（综合） | `type=61` 或 `xsort=time`（时间） | `weibo_playwright.py` |
| 3 | 输出文件名 | `weibo_real_{date}.jsonl` | `weibo_raw_{start}_{end}.jsonl` | `weibo_playwright.py` |
| 4 | 合并去重 | 不存在 | 按 weibo_id 合并 → `analysis_latest.jsonl` | 新增脚本或 `run_pipeline.py` |
| 5 | 看板数据加载 | 硬编码嵌入 HTML | 从 `analysis_latest.jsonl` 读取 | `dashboard.html` / `detail.html` 或生成脚本 |
| 6 | `spread_score` 字段 | 前端实时计算 | 建议在分析阶段写入 | `analyzer_v3.py` |
| 7 | `rules_triggered.matched_keywords` | 不存在 | 规格中提及 | `analyzer_v3.py` → `apply_rules()` |
| 8 | 辟谣文章匹配字段 | 仅知识库比对（`kb_matches`） | 需要 `is_piyao_match` + `piyao_confidence` | `analyzer_v3.py` |

---

## 附录 B：config.yaml 关键参数参考

```yaml
analyzer:
  risk_thresholds:
    critical: 8.0
    high: 5.0
    medium: 3.0
    low: 0.0
  weights:
    fear_words: 0.30
    absolute_words: 0.25
    fake_authority: 0.25
    product_link: 0.20
    testimony: 0.15

llm:
  model: glm-4-flash
  enabled: true
  timeout: 30
  max_tokens: 1024
  temperature: 0.1
```
