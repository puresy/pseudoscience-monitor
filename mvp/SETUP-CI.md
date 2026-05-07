# GitHub Actions 配置指南

## 快速开始

### 1. 配置 Secrets

在 GitHub 仓库设置中添加以下 Secrets：

**Settings → Secrets and variables → Actions → New repository secret**

| Secret 名称 | 说明 | 值 |
|-------------|------|-----|
| `XIAOMI_API_KEY` | 小米 Token Plan API Key | `tp-c9xvj5u57l05367ch601f0oi0ro328b1ugsrt4ywwr51kmud` |

### 2. 启用 Actions

1. 进入仓库 **Actions** 标签页
2. 点击 **I understand my workflows, go ahead and enable them**
3. 选择 **伪科普监测 - 每日采集分析**
4. 点击 **Enable workflow**

### 3. 手动测试

点击 **Run workflow** → 选择 `weibo` → 点击绿色按钮运行

---

## 定时任务说明

| 时间 | 说明 |
|------|------|
| 每天 03:00 (北京时间) | 微博采集 + 分析 |
| 每周日 03:00 | 额外更新辟谣知识库 |

**为什么选凌晨3点？**
- 小米 API 非高峰时段（00:00-08:00）有 0.8x 折扣
- 微博服务器负载较低

---

## 手动触发

```bash
# 使用 GitHub CLI
gh workflow run daily-pipeline.yml -f source=weibo -f limit=30

# 查看运行状态
gh run list --workflow=daily-pipeline.yml
```

---

## 数据产出

每次运行后会自动提交到仓库：

```
mvp/data/
├── weibo_real_YYYY-MM-DD.jsonl      # 原始采集
├── analysis_YYYY-MM-DD.jsonl         # 分析结果
└── rumor_knowledge_base.json         # 辟谣知识库
```

分析结果也会保存为 Actions Artifact（保留30天）。

---

## 常见问题

### Q: 采集失败怎么办？

检查 Actions 日志，常见原因：
1. 微博 API 限流 → 等待一段时间后重试
2. 网络问题 → GitHub 服务器有时访问微博不稳定

### Q: 怎么修改采集频率？

编辑 `.github/workflows/daily-pipeline.yml`：

```yaml
schedule:
  - cron: '0 19 * * *'  # 每天
  # - cron: '0 */12 * * *'  # 每12小时
  # - cron: '0 19 * * 1,3,5'  # 周一三五
```

### Q: 怎么看运行结果？

1. **Actions 页面**：查看每次运行的日志
2. **仓库 commits**：自动提交的数据文件
3. **Artifacts**：下载分析结果 JSONL

### Q: API Key 泄露了怎么办？

1. 去小米 Token Plan 后台重新生成 Key
2. 更新 GitHub Secret 中的 `XIAOMI_API_KEY`
3. 旧 Key 会自动失效
