# 交接文档 - 伪科普监测系统

> bon 写给 Cola，2026-05-04

---

## 一、我做了什么

### 阶段 0-4：引擎升级（analyzer_v3.py）

在原有 v3 引擎基础上做了以下改动：

| 改动 | 说明 |
|------|------|
| 危害主线检测 | `detect_harm_line()` 函数，识别电诈/风评受损/邪教三条线 |
| GRAY_ZONE | 新增内容类型，风险分 0.5-0.6 的灰色内容触发 LLM 二次判定 |
| R7 规则 | 科学滥用单独检测（不需要夸大成分） |
| n-gram 知识库匹配 | `_tokenize_chinese()` 2-4字切词，解决长句匹配失败 |
| 关键词扩展 | SCIENCE_ABUSE_WORDS +15, DEBUNK_WORDS +12, FAKE_AUTHORITY_WORDS +6 |
| 源权重调整 | 认证媒体/政府号 risk_score × 0.5（原 0.7） |
| R5 排除逻辑 | 辟谣/休闲场景下不触发食物相克规则 |

**测试结果**（435条基线）：
- PSEUDOSCIENCE: 21→85条（4.8%→19.5%）
- NORMAL_SCIENCE: 308→218条（70.8%→50.1%）
- PSEUDOSCIENCE F1: 0.67

### 阶段 6：传播分析器（propagation_analyzer.py）

新建模块，功能：
- 内容聚类（SequenceMatcher 相似度）
- 矩阵号检测（同一账号批量发相似内容）
- 跨平台追踪
- CLI 支持多文件输入、JSON 输出

**状态**：代码完成，未用真实数据验证（老数据没有 text 字段）

### 阶段 7：报告生成器（report_agent.py）

新建模块，功能：
- 读取 JSONL 研判结果
- 输出结构化周报（数据总览、危害主线、重点事件、趋势建议）
- CLI 支持周数/日期参数

**状态**：已测试通过（435条数据），但老数据缺 text/keyword/harm_line 字段，摘要为空

### 阶段 8：工程化模块

| 文件 | 功能 | 状态 |
|------|------|------|
| `config.py` | 统一配置管理，支持 JSON + 环境变量 | 完成 |
| `cookie_manager.py` | 多平台 Cookie 管理（JSON/txt） | 完成 |
| `cost_tracker.py` | LLM API 成本追踪与限制 | 完成 |
| `health_check.py` | 系统健康检查（11项正常） | 完成 |
| `crawlers/base.py` | 采集器基类 | 完成 |
| `crawlers/bilibili.py` | B站采集器 | 412反爬，未跑通 |
| `crawlers/zhihu.py` | 知乎采集器 | 400需认证，未跑通 |
| `crawlers/weixin.py` | 微信采集器 | 未验证 |

### 看板更新（dashboard.html）

- 数据从 v1 更新到 v3.1（85/58/218/73）
- 版本标签、危害主线、知识库信息已更新
- 已 commit 并 push 到 `puresy/pseudoscience-monitor`

---

## 二、没做完的事

### 1. 采集器没跑通（最大问题）

B站/知乎采集器都有反爬。刚装了 Scrapling（43k stars，绕 Cloudflare），测试中：

- StealthyFetcher 能拿到 B站搜索页 200
- 但 B站是 SPA，文本提取有问题（Vue 渲染，`text` 为空）
- 还没调通选择器

**Scrapling 已安装**：`pip3 install "scrapling[all]"`，Playwright Chromium 已装好

### 2. 没有新数据

所有分析都是基于 4/23-4/24 的 435 条老数据。系统能分析但没在"看"。

### 3. 传播分析器未验证

代码写好了但没用真实数据跑过（老数据没有 text 字段）。

### 4. Phase 5 跳过了

Phase 5 是"7天真实采集"，直接跳到了 Phase 6/7/8。

---

## 二、IMPROVEMENTS.md 落地（13:30更新）

Cola 写的改进点，我做了能做的部分：

### 1. 源配置文件化 ✅

**文件**：`sources.json`
- 54个种子词，7个分类（恐惧营销/伪权威/科学滥用/食品安全/健康养生/营销导向/高频主题）
- 4个平台配置（微博启用，B站/知乎/微信待启用）
- 淘汰规则参数化（试用7天，连续7天0产出降权，14天淘汰）

### 2. 源健康度 + 淘汰机制 ✅

**文件**：`source_health.py`
- 追踪每个种子词的信息密度（每日采集量、伪科普产出）
- 试用期管理（新种子词跑7天，≥1条伪科普才采纳）
- 低产出降权/淘汰
- CLI：`python source_health.py report/check/status`

### 3. Jina Reader 兜底 ✅

**文件**：`jina_reader.py`
- 接入 r.jina.ai 做 Markdown 转换
- 支持批量获取、纯文本/Markdown 模式
- 测试：成功获取 piyao 主页 18461 字符

### 4. RSS/辟谣网站接入 ✅（部分）

**发现**：
- piyao.kepuchina.cn 无 RSS（/rss 返回 404）
- kepuchina.cn 也无 RSS

**替代方案**：
- **文件**：`piyao_scraper.py`
- 用 Jina Reader 抓取主页，提取辟谣详情链接
- 支持反向种子词提取（从辟谣帖中提取谣言主张作为新监测目标）
- 测试：4条辟谣详情 + 6个反向种子词

### 5. 定时跑 + JSON 模式 ⏳

未做。需要：
- GitHub Actions 配置
- pipeline 输出 JSON 到 data/
- GitHub Pages 自动更新

**建议**：这个让 Cola 来做，涉及 CI/CD 配置。

---

## 三、文件位置

```
mvp/
├── analyzer_v3.py          # 主引擎（已改动）
├── propagation_analyzer.py # 传播分析（新建）
├── report_agent.py         # 报告生成（新建）
├── config.py               # 配置管理（新建）
├── cookie_manager.py       # Cookie管理（新建）
├── cost_tracker.py         # 成本追踪（新建）
├── health_check.py         # 健康检查（新建）
├── sources.json            # 源配置（新建）
├── source_health.py        # 源健康度追踪（新建）
├── jina_reader.py          # Jina Reader 兜底（新建）
├── piyao_scraper.py        # 辟谣采集器（新建）
├── dashboard.html          # 看板（已更新数据）
├── crawlers/
│   ├── base.py             # 基类（新建）
│   ├── bilibili.py         # B站（需Scrapling重写）
│   ├── zhihu.py            # 知乎（需Scrapling重写）
│   └── weixin.py           # 微信（未验证）
└── data/
    ├── baseline_v2_2026-05-03.jsonl  # 435条基线
    ├── rumor_knowledge_base.json     # 31条辟谣知识库
    ├── source_health.json            # 源健康度数据（新建）
    └── test_report.md                # 测试报告
```

---

## 四、关键代码位置

**危害主线检测**：`analyzer_v3.py` → `detect_harm_line()` 函数
**GRAY_ZONE**：`analyzer_v3.py` → `_tokenize_chinese()` + 分类逻辑
**n-gram 匹配**：`analyzer_v3.py` → `check_against_knowledge_base()`
**R7 规则**：`analyzer_v3.py` → `analyze_content()` 中的规则列表

---

## 五、已知问题

1. **Telegram 通知格式**：带 markdown 格式的消息会报 400 错误，纯文本可以
2. **知识库格式**：`rumor_knowledge_base.json` 是 `{articles: {url: {...}}}` 格式，health_check 里已适配
3. **老数据字段缺失**：baseline JSONL 没有 text/keyword/harm_line 字段，导致传播分析和报告摘要为空

---

## 六、建议优先级

1. **P0**：用 Scrapling 重写 B站采集器，让系统能采到新数据
2. **P1**：跑一次完整采集 + 分析，验证端到端流程
3. **P2**：GitHub Actions 定时跑（IMPROVEMENTS.md 第2点）
4. **P3**：用新数据测试传播分析器
5. **P4**：知乎/微信采集器接入

---

## 七、Git 状态

- 仓库：`https://github.com/puresy/pseudoscience-monitor`
- 本地：`~/Projects/pseudoscience-monitor`
- 最新 commit：`020efe4` feat: v3.1引擎升级 + 工程化模块 + 看板数据更新
- 代理：需要 `https_proxy=http://localhost:7890` 才能 push

---

**最后更新**：2026-05-04 12:00
**写文档的人**：bon (bonjour MacBook Air)
