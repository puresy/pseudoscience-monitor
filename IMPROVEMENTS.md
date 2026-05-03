## 伪科普监测项目 — 借鉴 ai-news-radar 的改进点

参考项目：https://github.com/LearnPrompt/ai-news-radar
核心思路：信息源采集 → 结构化JSON → GitHub Pages静态发布，定时跑不需要服务器常驻。

### Action List

**1. 源健康度 + 淘汰机制**
- 给每个种子词/信息源加"信息密度"指标：过去7天采集到的有效伪科普条数
- 连续一周贡献0条PSEUDOSCIENCE的种子词降权或淘汰
- 新增种子词时有个"试用期"：跑7天看产出，低于阈值不入正式库
- 目的：解决"扩词后噪音爆炸"问题，不是无限扩，是扩完再砍

**2. 定时跑 + 推JSON模式**
- 当前如果是手动触发pipeline，改为 GitHub Actions 定时触发（如每天2次）
- pipeline跑完输出结构化JSON到 `data/` 目录，GitHub Pages自动更新dashboard
- 不需要Agent持续在线，降低成本

**3. Jina Reader 兜底**
- 对解析困难的页面（微博长文、某些网页），接入 jina reader (r.jina.ai) 做Markdown转换
- 作为采集层的fallback，不是主路径

**4. RSS/辟谣网站批量接入**
- 检查科学辟谣网站（piyao.org.cn）是否有RSS feed
- 如果有，批量接入作为"反向种子"——辟谣帖里提到的谣言主张可以自动提取为新的监测目标
- 比手动扩词更系统

**5. 源配置文件化**
- 把种子词库、信息源列表、淘汰规则写成一个 `sources.json` 或 `sources.yaml`
- 新增/删除源只改配置文件，不改代码
- 方便后续扩展到公众号接口等新数据源

### 不需要搬的
- ai-news-radar 的去重是URL级别，我们需要"科学主张级别"归并（同一谣言不同表述归为一条），这个比他复杂，保持现有方案
- 他不需要分类引擎，我们的LLM分类层保持不变
- 浏览器自动化（他也说了不做）——我们也不做，保持被动采集
