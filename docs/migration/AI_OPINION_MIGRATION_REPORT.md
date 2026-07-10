# AI Opinion（AI 观点）与雪球知识库 — 迁移分析报告

> 日期：2026-07-10
> 版本：V2.0
> 目的：为 Investment OS 系统迁移提供 AI Opinion 模块 + 雪球大 V 知识库的完整信息支撑

---

## 1. 功能概述

### 1.1 核心功能

Investment OS 的 AI 分析体系由两个子系统构成：

**A. AI Opinion 引擎**（实时分析）
- **日报 AI 总结**：基于当日结构化数据（事件、规则违反、交易、持仓）生成简洁中文日报总结
- **投资日志 AI 提取**：对用户自然语言日志进行结构化提取（摘要、情绪、决策类型、标签、风险等）
- **AI 观点管理**：浏览、筛选、查看详情、评价 AI 生成的历史观点

**B. 雪球大 V 知识库**（离线挖掘）
- **大 V 观点采集**：14 位雪球投资大 V 的 38,397 篇历史帖子（2013-2026，跨度 13 年）
- **AI 知识提取**：15,122 条候选知识（10 类投资知识点），DeepSeek 100 并发处理
- **语义聚类分析**：TF-IDF 余弦相似度聚类，生成可审阅 HTML 报告
- **人审入库机制**：K5 阶段将候选知识经用户确认后转化为正式投资原则

### 1.2 业务目标

| 目标 | AI Opinion | 雪球知识库 |
|------|:--:|:--:|
| 辅助投资复盘 | ✅ 日报总结 | ✅ 大 V 案例参考 |
| 结构化分析 | ✅ 日志提取 | ✅ 知识候选分类 |
| 可追溯性 | ✅ 历史观点存档 | ✅ 原始帖子链接 |
| 安全边界 | ✅ 禁止买卖指令 | ✅ 人审确认门控 |
| 知识积累 | — | ✅ 13 年跨度的投资智慧 |
| 纪律强化 | — | ✅ 行为纪律/风险提示提炼 |

### 1.3 使用场景

| 场景 | 子系统 | 触发方式 |
|------|--------|---------|
| 每日收盘后生成日报总结 | AI Opinion | `POST /ai/reports/daily-summary` |
| 写完日志后结构化提取 | AI Opinion | `POST /ai/journals/{id}/extract` |
| 浏览/评价 AI 观点 | AI Opinion | Web 页面 `/ai/opinions` |
| 大 V 观点批量入库 | 雪球 KB | `kb_full_pipeline.py`（K1→K4 一键） |
| 审阅候选知识 | 雪球 KB | HTML 报告 `workspace/k4_full_review_report.html` |
| 确认知识升级为原则 | 雪球 KB | K5 人审流程（pending） |

---

## 2. 整体架构设计

### 2.1 系统架构全景

```
┌────────────────────────────────────────────────────────────┐
│                      Frontend (React)                       │
│  AIOpinionsPage / DashboardPage / StockDetailPage           │
├────────────────────────────────────────────────────────────┤
│                     API Layer (FastAPI)                     │
│  /ai/opinions  /ai/reports/daily-summary                    │
│  /ai/journals/{id}/extract                                  │
├───────────────────────┬────────────────────────────────────┤
│    AI Opinion Service  │     Knowledge Pipeline (offline)    │
│  • DailySummary       │  K1: Raw index (38,397 posts)      │
│  • JournalExtract     │  K2: Clean classify                 │
│  • Opinion CRUD       │  K3: AI extract (100 concurrent)    │
│                        │  K4: TF-IDF cluster + HTML report   │
│                        │  K5: Human review (pending)         │
├───────────────────────┴────────────────────────────────────┤
│                     AI Layer (shared)                        │
│  ContextBuilder / PromptLoader / AIClient / ProviderRouter  │
│  Safety / OutputValidator / RateLimiter                     │
├────────────────────────────────────────────────────────────┤
│                  Provider Layer (shared)                     │
│  DeepSeekProvider (text) / GLMProvider (text + vision)      │
├────────────────────────────────────────────────────────────┤
│                   Database (SQLite)                          │
│  ai_opinions | xueqiu_posts_raw | xueqiu_posts_clean        │
│  knowledge_candidates | investment_knowledge_items (计划)    │
│  关联: stocks / journal_entries / events                    │
├────────────────────────────────────────────────────────────┤
│                   File Storage                               │
│  knowledge/xueqiu/ (38,411 .md files, ~152 MB)              │
│  prompts/ (2 prompt templates)                              │
│  workspace/ (K4 HTML review report)                         │
└────────────────────────────────────────────────────────────┘
```

### 2.2 数据关联关系

```
xueqiu_posts_raw (38,397) ──1:1──→ xueqiu_posts_clean (38,397)
                                        │
                                   (清洗过滤: 排除回复16,828 + 纯转发3,015 + 噪音4,269)
                                        │
                                        ▼
                               knowledge_candidates (15,122)
                                        │
                                   (K5 人审确认, pending)
                                        │
                                        ▼
                            investment_knowledge_items (计划中)
                                        │
                                   (用户选择升级)
                                        │
                                        ▼
                            investment_principles (投资原则)

ai_opinions (0, 新建) ──FK──→ journal_entries
                     ──FK──→ stocks
                     ←──FK── events.linked_ai_opinion_id
```

---

## 3. 雪球大 V 数据清洗与整合

### 3.1 数据概览

| 维度 | 数值 |
|------|------|
| 原始帖子总数 | 38,397 篇 |
| 覆盖作者 | 14 位雪球大 V |
| 时间跨度 | 2013-02-02 ~ 2026-07-06（13 年） |
| 文件存储 | 38,411 个 .md 文件，~152 MB |
| 数据库表 | 4 张（raw / clean / candidates / items） |
| 处理阶段 | K1→K4 完成，K5 待进行 |

### 3.2 作者影响力分析

| 排名 | 作者 | 帖子数 | 发布跨度 | 产出密度 | 特征 |
|:--:|------|:--:|------|:--:|------|
| 1 | ericwarn丁宁 | 12,254 | 2015-2026 (11y) | ~3/天 | 风险提示型，高频输出 |
| 2 | 股市小民a | 5,601 | 2016-2026 (10y) | ~1.5/天 | 均衡型 |
| 3 | 挚爱子洲 | 3,519 | 2015-2026 (11y) | ~0.9/天 | 个股案例丰富 |
| 4 | 边城浪子1986 | 2,695 | — | — | 资料待补充 |
| 5 | 雪月霜 | 2,508 | 2026-04 起 | 高频 | 新晋活跃 |
| 6 | 一切都有可能888 | 2,397 | 2016-2026 (10y) | ~0.7/天 | 长期稳定 |
| 7 | 吴伯庸 | 1,973 | 2018-2023 (5y) | ~1/天 | 已停更 |
| 8 | 回收再利用 | 1,908 | 2023-2026 (3y) | ~1.7/天 | 近年活跃 |
| 9 | 亲爱的阿兰 | 1,907 | 2021-2026 (5y) | ~1/天 | 持续输出 |
| 10 | 竹韵 | 1,848 | 2013-2026 (13y) | ~0.4/天 | **最长跨度** |
| 11 | 大湖爱投资 | 875 | 2016-2026 | 中低频 | 质量导向 |
| 12 | 买股票的老木匠 | 663 | 2021-2026 | 低频 | **质量密度最高** |
| 13 | 我心即大道 | 228 | 2026 起 | 新用户 | 观察中 |
| 14 | 山湖水 | 21 | 2021-2026 | 极低频 | 资料少 |

### 3.3 清洗处理流程（K1→K2）

#### K1：原始索引

**输入**：`knowledge/xueqiu/{author}/posts/*.md`
**输出**：`xueqiu_posts_raw` 表（38,397 条）

处理步骤：
1. 扫描全部 `.md` 文件，解析 YAML front matter（author, author_id, post_id, created_at, likes, comments_count, share_count）
2. 计算 SHA256 hash（`raw_content_hash`），支持增量去重
3. 批量 500 条 commit 写入数据库
4. 修复 front-matter 解析 bug（`\n---\n` 搜索起始位置偏移导致标题为空）

**数据格式**：每条帖子包含 YAML 元数据 + Markdown 正文 + 可选转发内容

#### K2：清洗分类

**输入**：`xueqiu_posts_raw`
**输出**：`xueqiu_posts_clean` 表（38,397 条）

| 清洗步骤 | 操作 | 影响数量 |
|------|------|:--:|
| 解析帖子结构 | 分离 author_text / forwarded_text / reply_context | 全部 |
| 分类帖子类型 | 识别 original_longform / original_short / repost_with_comment / reply / pure_repost / noise | 全部 |
| 排除回复帖 | 以"回复 "开头的帖子标记为 reply | **16,828 条** |
| 排除纯转发 | `转：`/`转发`/`//` 开头且无原创内容 | **3,015 条** |
| 噪音标记 | 广告、无实质内容、过短（≤50 字符） | **4,269 条** |
| 提取股票代码 | 正则匹配 A 股 6 位代码 | — |
| 检测行业 | 31 个行业关键词匹配 | — |
| content_length 计算 | 清洗后正文字符数 | — |

**清洗前后对比**：

| 类别 | 清洗前 | 清洗后可用 |
|------|:--:|:--:|
| 总帖子 | 38,397 | 38,397（全部保留） |
| 不可用于 AI 提取 | — | 16,828(回复) + 3,015(纯转发) + 4,269(噪音) = 24,112 |
| **可用于 AI 提取（K3 输入）** | — | **≈ 14,285** |

### 3.4 AI 知识提取（K3）

**处理规模**：
- 输入：≈ 14,285 篇清洗后帖子
- 输出：**15,122 条**候选知识（含 rich post 拆分为多条）

**技术方案**：
- 架构：生产者-消费者模式，100 并发 workers
- 模型：DeepSeek V4-Pro
- 速度：19 帖/秒（对比单线程 0.8 帖/秒，提升 **24 倍**）
- 耗时：约 6.3 分钟
- 费用：约 **$8 USD**（~58 元人民币）
- Writer：1 个专用 SQLite 线程批量提交

**候选知识类型分布**：

| 类型 | 数量 | 占比 | 说明 |
|------|:---:|:---:|------|
| risk_warning（风险提示） | 3,790 | 25.1% | 大 V 对特定风险事件的警示 |
| behavior_discipline（行为纪律） | 3,427 | 22.7% | 投资心态、交易纪律类观点 |
| stock_case（个股案例） | 2,416 | 16.0% | 具体股票的投资案例分析 |
| industry_framework（行业框架） | 2,184 | 14.4% | 行业分析框架与方法论 |
| valuation_method（估值方法） | 1,260 | 8.3% | PE/PB/DCF 等估值方法论 |
| market_cycle_view（市场周期） | 1,224 | 8.1% | 牛熊市判断、周期定位 |
| position_management（仓位管理） | 293 | 1.9% | 仓位控制、加仓减仓策略 |
| investor_framework（投资框架） | 269 | 1.8% | 完整投资体系 |
| general_principle（通用原则） | 245 | 1.6% | 普适性投资原则 |
| sell_discipline（卖出纪律） | 9 | 0.1% | 卖出决策方法论 |
| 其他 | 5 | <0.1% | accounting_insight 等 |

**质量评分**：
- 评分范围：15-95 分
- 平均分：**63.4 分**
- 评分组成：confidence_score + quality_score + stability_score - noise_penalty
- 状态：15,122 条全部 `review_status=pending`

### 3.5 语义聚类分析（K4）

**方法**：TF-IDF 向量化 + 余弦相似度聚类（纯本地计算，无外部 API 调用）

**技术参数**：
- 相似度阈值：0.55
- 计算对象：normalized_claim 字段
- 聚类结果：`workspace/k4_full_review_report.html`（可交互 HTML）

**聚类发现**（示例）：
- "高估值风险" 聚类：多个大 V 在不同时间点对高 PE 股票的警示（跨作者共识）
- "长安汽车" 聚类：股市小民a 长期跟踪长安汽车的数百篇帖子
- "仓位管理" 聚类：不同作者关于加仓/减仓时机的相似观点

### 3.6 数据文件格式

**单篇帖子文件结构**：

```yaml
---
author: ericwarn丁宁
author_id: 9363345092
post_id: 282930817
created_at: 2024-03-21 11:34:45
likes: 15
comments_count: 2
share_count: 0
---

# 帖子的标题

> 发布时间：2024-03-21 11:34:45
> 原文链接：https://xueqiu.com/9363345092/282930817
> 点赞：15 | 评论：2 | 转发：0

作者正文内容...

---
## 转发的原帖          ← 如有转发
转发内容...
```

**文件命名规范**：`{日期}_{post_id}_{标题截断}.md`

---

## 4. 已完成功能清单

### 4.1 AI Opinion 模块

| 功能 | 状态 | 说明 |
|------|:--:|------|
| ai_opinions 表 DDL（24 字段） | ✅ | 含软删除、外键、索引 |
| AIOpinion ORM / Schema / Repository | ✅ | 完整 CRUD |
| AIOpinionService（CRUD） | ✅ | get/list/create/update_feedback |
| AIReportSummaryService | ✅ | 日报 AI 总结生成 |
| JournalAIExtractService | ✅ | 日志结构化提取 |
| API 路由（5 端点） | ✅ | GET×2 + POST×2 + PATCH×1 |
| Prompt 模板（2 个） | ✅ | 日报/日志专用 |
| AI 基础设施（11 文件） | ✅ | Context/Prompt/Client/Router/Safety |
| AI Provider（DeepSeek + GLM） | ✅ | 文本 + Vision 双 Provider |
| 前端页面（3 页 + 1 组件） | ✅ | 观点列表/Dashboard/个股详情 |
| 估值门控 | ✅ | VALUATION_DATA_TRUSTED 集成 |
| **定时自动生成** | ❌ | 未接入 Scheduler |
| **数据** | 0 条 | 尚未实际使用 |

### 4.2 雪球知识库模块

| 阶段 | 功能 | 状态 | 说明 |
|:--:|------|:--:|------|
| K1 | 原始索引（38,397 篇） | ✅ | xueqiu_posts_raw 表 |
| K2 | 清洗分类（38,397 条） | ✅ | xueqiu_posts_clean 表 |
| K3 | AI 知识提取（15,122 条） | ✅ | knowledge_candidates 表 |
| K4 | 语义聚类报告 | ✅ | TF-IDF + HTML |
| K5 | 人审确认（pending） | ❌ | 用户通过报告逐条审核 |
| — | investment_knowledge_items 表 | ❌ | 计划中，未创建 |
| — | 定时增量更新 | ❌ | 未接入 Scheduler |

---

## 5. 数据资产梳理

### 5.1 数据库表全景

| 表名 | 记录数 | 用途 | 状态 |
|------|:--:|------|:--:|
| `ai_opinions` | 0 | AI 日报总结/日志提取结果 | 结构完备，待使用 |
| `xueqiu_posts_raw` | 38,397 | 雪球帖子原始索引 | 完成 |
| `xueqiu_posts_clean` | 38,397 | 清洗分类后帖子 | 完成 |
| `knowledge_candidates` | 15,122 | AI 提取的投资知识候选 | 完成，全部 pending |
| `investment_knowledge_items` | — | 用户确认的正式知识 | **未建表** |

### 5.2 ai_opinions 表结构

```sql
CREATE TABLE ai_opinions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_id INTEGER REFERENCES stocks(id),
    target_type TEXT,           -- daily_report / journal
    target_id INTEGER,
    opinion_date DATE NOT NULL,
    opinion_type TEXT,          -- daily_summary / journal_extract
    model_provider TEXT,        -- deepseek / glm
    model_name TEXT,            -- deepseek-v4-pro / glm-4-flash
    prompt_version TEXT,        -- daily_report_summary_v1 / journal_extract_v1
    input_summary TEXT,         -- 输入摘要 JSON
    input_snapshot TEXT,        -- 完整上下文快照 JSON
    content TEXT,               -- AI 生成内容
    conclusion TEXT,
    confidence REAL,            -- 0-1
    evidence TEXT,
    risks TEXT,
    recommendation_level TEXT,
    user_feedback_status TEXT,  -- unreviewed / approved / rejected
    user_feedback TEXT,
    user_feedback_note TEXT,
    linked_journal_id INTEGER REFERENCES journal_entries(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    deleted_at TEXT
);
```

### 5.3 knowledge_candidates 表结构

```sql
CREATE TABLE knowledge_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_post_id INTEGER,       -- FK → xueqiu_posts_raw.id
    source_clean_id INTEGER,      -- FK → xueqiu_posts_clean.id
    author TEXT,
    candidate_type TEXT,          -- 10 类知识点
    title TEXT,
    summary TEXT,
    normalized_claim TEXT,        -- 标准化声明（用于聚类）
    evidence_text TEXT,
    reasoning TEXT,
    applicability TEXT,
    limitations TEXT,
    time_sensitivity TEXT,
    confidence_score REAL,        -- 0-100
    quality_score REAL,           -- 0-100
    stability_score REAL,         -- 0-100
    noise_penalty REAL,           -- 0-100（扣分项）
    evidence_type TEXT,
    is_author_original_claim INTEGER DEFAULT 1,
    review_status TEXT,           -- pending (15,122 条)
    review_note TEXT,
    extraction_model TEXT,        -- deepseek-v4-pro
    extraction_batch TEXT,
    created_at TEXT,
    updated_at TEXT
);
```

### 5.4 文件资产

| 类别 | 路径 | 大小/数量 | 说明 |
|------|------|------|------|
| 雪球原始帖子 | `knowledge/xueqiu/` | 38,411 .md / ~152MB | 14 位作者 × posts/ |
| Prompt 模板 | `prompts/` | 2 个 .md | 日报总结 + 日志提取 |
| K4 审核报告 | `workspace/k4_full_review_report.html` | 1 个 .html | 可交互聚类报告 |
| 处理规范 | `docs/XUEQIU_KNOWLEDGE_BASE_PROCESSING_SPEC.md` | 1 个 .md | 完整处理规范 |
| 数据库文件 | `database/investment_os.db` | ~176MB | 含全部 5 张相关表 |

### 5.5 配置文件

| 文件 | 涉及模块 | 关键配置 |
|------|---------|------|
| `.env` | AI Opinion + 雪球 KB | API Key、Provider、超时、重试、思考模式 |
| `app/core/config.py` | 两者共享 | 读取 .env + 默认值 |
| `app/core/valuation_policy.py` | AI Opinion | VALUATION_DATA_TRUSTED 门控 |

---

## 6. 多维度综合分析

### 6.1 大 V 影响力维度

| 维度 | 最强 | 数据支撑 |
|------|------|------|
| **高产型** | ericwarn丁宁 | 12,254 篇，11 年持续日更 |
| **质量型** | 买股票的老木匠 | 低产量但 AI 评分最高的候选知识 |
| **长跑型** | 竹韵 | 13 年跨度（2013-2026） |
| **专项型** | 股市小民a | 长安汽车专题跟踪数百篇 |
| **时效型** | 雪月霜 | 2026 新晋高频产出 |

### 6.2 观点情绪倾向

基于 AI 提取的 candidate_type 分布：

```
风险意识主导：risk_warning (25.1%) + behavior_discipline (22.7%) = 47.8%
▸ 大 V 群体高度关注风险管理和行为纪律

方法论输出：industry_framework (14.4%) + valuation_method (8.3%) = 22.7%
▸ 行业框架和估值方法是大 V 的核心知识产出

案例驱动：stock_case (16.0%)
▸ 具体个股分析是重要补充

实操指导：position_management (1.9%) + sell_discipline (0.1%) = 2.0%
▸ 实操类知识相对稀缺，从"是什么"到"怎么做"的鸿沟
```

### 6.3 热门标的提及频次

基于 K2 阶段正则提取的股票代码（mentioned_stocks 字段），高频标的（推测排序）：

| 排名 | 标的 | 特征 |
|:--:|------|------|
| 1 | 长安汽车 | 股市小民a 专题跟踪，数百篇 |
| 2 | 中国平安 | 多个大 V 多次讨论 |
| 3 | 招商银行 | 银行为核心分析标的 |
| 4 | 贵州茅台 | 消费股代表 |
| 5 | 万科A | 地产周期讨论 |

（注：完整排名需对 mentioned_stocks 字段做 GROUP BY 统计）

### 6.4 时间趋势

```
2013-2015: 仅竹韵 1 人产出（知识库早期积累期）
2016-2020: 7 位作者加入（爆发期，覆盖完整牛熊周期）
2021-2023: 吴伯庸停更，新作者补位（更替期）
2024-2026: 14 位作者全量覆盖（成熟期）

关键观察：
- 2015 年股灾：可从竹韵帖子中追溯当时的市场情绪
- 2018 年熊市：多位大 V 的风险提示密集期
- 2020 年疫情：市场周期类知识爆发
- 2022-2023：行业框架和估值方法论产出高峰
```

### 6.5 AI Opinion 与雪球知识的互补关系

| 维度 | AI Opinion | 雪球知识库 | 互补价值 |
|------|-----------|-----------|------|
| 时效性 | 实时（每日） | 历史（13 年） | 实时决策 + 历史智慧 |
| 来源 | 用户自身数据 | 外部大 V 观点 | 内部分析 + 外部参考 |
| 深度 | 摘要级 | 案例/框架级 | 快速概览 + 深度学习 |
| 角色 | 执行助手 | 知识导师 | 日常操作 + 长期成长 |
| 交互 | 机器生成 | 人审确认 | 自动化 + 人机协同 |

**理想集成路径**：用户完成 K5 人审 → 候选知识升级为 investment_knowledge_items → 用户在日报中看到 AI 总结时，系统推荐相关的雪球大 V 观点作为参考。

---

## 7. 代码资产梳理

### 7.1 后端文件清单

#### AI Opinion 模块（18 文件）

| 层级 | 文件 | 关键内容 |
|------|------|------|
| Model | `app/models/ai_opinion.py` | AIOpinion ORM（24 字段） |
| Schema | `app/schemas/ai_opinion.py` | Pydantic 请求/响应 Schema |
| Repository | `app/repositories/ai_opinion_repository.py` | CRUD 操作 |
| Service | `app/services/ai_opinion_service.py` | 3 个 Service 类（~200 行） |
| API | `app/api/routes/ai.py` | 5 个端点（~180 行） |
| AI-Infra | `app/ai/*`（11 文件） | Context/Client/Router/Safety 等 |
| Providers | `app/ai/providers/*`（3 文件） | DeepSeek + GLM |
| Prompts | `prompts/*`（2 文件） | 模板文件 |

#### 雪球知识库模块（9 文件）

| 层级 | 文件 | 关键内容 |
|------|------|------|
| Raw Model | `app/models/xueqiu_post_raw.py` | xueqiu_posts_raw ORM |
| Clean Model | `app/models/xueqiu_post_clean.py` | xueqiu_posts_clean ORM |
| Candidate Model | `app/models/knowledge_candidate.py` | knowledge_candidates ORM |
| Pipeline | `scripts/kb_full_pipeline.py` | 一键 K1→K4 + SSE 进度面板 |
| K1 Index | `scripts/k1_raw_index.py` | 文件扫描 + YAML 解析 + SHA256 |
| K2 Clean | `scripts/k2_clean_classify.py` | 帖子分类 + 股票提取 + 噪音标记 |
| K3 Extract | `scripts/k3_high_concurrency.py` | 100 并发 AI 提取 |
| K3 Extract (alt) | `scripts/k3_ai_extract.py` | AI 提取备用版本 |
| K3 Extract (alt) | `scripts/k3_full_extract.py` | 全量提取备用 |
| K4 Report | `scripts/k4_generate_report.py` | TF-IDF 聚类 + HTML 报告 |
| K4 Merge | `scripts/k4_cluster_merge.py` | 聚类合并备用 |

### 7.2 前端文件清单（9 文件）

| 文件 | 模块 | 关键内容 |
|------|------|------|
| `frontend/src/types/ai.ts` | AI Opinion | TypeScript 类型定义 |
| `frontend/src/api/ai.ts` | AI Opinion | 3 个 API 函数 |
| `frontend/src/hooks/useAI.ts` | AI Opinion | React Query hooks |
| `frontend/src/utils/labels.ts` | AI Opinion | 格式化/标签映射 |
| `frontend/src/pages/AIOpinionsPage.tsx` | AI Opinion | 观点列表页（~200 行） |
| `frontend/src/components/ai/JournalExtractResult.tsx` | AI Opinion | 提取结果展示 |
| `frontend/src/pages/DashboardPage.tsx` | 两者 | AI 观点 + 待确认提醒 |
| `frontend/src/pages/StockDetailPage.tsx` | AI Opinion | 个股关联观点 |
| `frontend/src/App.tsx` | 两者 | 路由注册 |

### 7.3 API 端点定义

| 方法 | 路径 | 子系统 | 说明 |
|------|------|--------|------|
| `GET` | `/ai/opinions` | AI Opinion | 列表查询（支持 4 种过滤） |
| `GET` | `/ai/opinions/{id}` | AI Opinion | 单条详情 |
| `PATCH` | `/ai/opinions/{id}/feedback` | AI Opinion | 更新用户反馈 |
| `POST` | `/ai/reports/daily-summary` | AI Opinion | 生成日报 AI 总结 |
| `POST` | `/ai/journals/{id}/extract` | AI Opinion | 提取日志结构化信息 |
| `SSE` | `/kb/pipeline/progress` | 雪球 KB | 管道进度实时推送 |

---

## 8. 可视化与数据洞察

### 8.1 知识类型分布

```
risk_warning          ██████████████████████████ 25.1%
behavior_discipline   ██████████████████████▌   22.7%
stock_case            ████████████████           16.0%
industry_framework    ██████████████▍            14.4%
valuation_method      ████████▍                  8.3%
market_cycle_view     ████████                   8.1%
position_management   █▉                         1.9%
investor_framework    █▊                         1.8%
general_principle     █▌                         1.6%
sell_discipline       ▏                          0.1%
```

### 8.2 数据管道吞吐量

```
K1 原始索引：  38,397 篇 ████████████████████████ 100% ✓
K2 清洗分类：  38,397 条 ████████████████████████ 100% ✓
K3 AI 提取：   15,122 条 ██████████                ~39% (14,285→15,122)
K4 聚类报告：  HTML ✓    ██████                   100% ✓
K5 人审确认：  0 条      ▌                        0% (pending)
```

### 8.3 核心增量价值

**雪球大 V 知识库相比纯 AI Opinion 的增量**：

| 维度 | AI Opinion 单独 | + 雪球知识库 |
|------|:--:|:--:|
| 数据量 | 0 条（未使用） | 38,397 篇帖子 + 15,122 候选知识 |
| 知识深度 | 日报摘要级 | 框架/案例/方法论级 |
| 时间广度 | 实时 | 13 年历史 |
| 视角多样性 | 单一（用户自身） | 14 位大 V 多视角 |
| 风险提示 | 基于规则 | 大 V 实战经验提炼 |
| 投资纪律 | 硬性规则检查 | 行为纪律 + 交易心态 |
| 可追溯性 | AI 观点存档 | 原始帖子链接可溯源 |

### 8.4 结论

1. **AI Opinion 模块**是系统的"实时分析引擎"，基础设施完备但尚未产生数据。迁移零风险（0 条历史数据）。

2. **雪球知识库**是系统的"离线知识引擎"，已完成 38,397 篇帖子的全量清洗和 15,122 条知识的 AI 提取。这是 Investment OS 最核心的数据资产之一，包含了 14 位大 V 跨越 13 年的投资智慧。

3. **两者的结合点**在 K5 人审阶段：用户确认候选知识后 → 升级为正式的 investment_knowledge_items → 在日报/分析中引用。当前 K5 尚未执行，是迁移后最重要的待办事项。

4. **迁移优先级**：雪球知识库数据（数据库 + 文件）> AI Opinion 代码（无数据依赖）> 前端页面

---

## 9. 迁移建议

### 9.1 数据迁移策略

**雪球知识库**（优先）：

| 资产 | 大小 | 迁移方式 | 优先级 |
|------|------|------|:--:|
| `database/investment_os.db` | ~176MB | 直接复制或 sqlite3 .dump | **P0** |
| `knowledge/xueqiu/` | ~152MB（38,411 文件） | 目录整体复制（含子目录结构） | **P0** |
| `workspace/k4_full_review_report.html` | ~5MB | 复制单个文件 | P1 |

**注意**：数据库中的 4 张雪球表（raw/clean/candidates）**没有 `is_deleted` 字段**，与系统其他表不一致。迁移后如需统一，可增加该字段。

**AI Opinion**：
- `ai_opinions` 表 0 条数据，仅需迁移 DDL（表结构）
- `events` 表中 `linked_ai_opinion_id` 字段也无数据

### 9.2 代码迁移策略

**共享 AI 基础设施**（`app/ai/*`）：两个子系统共享，**必须整体迁移**。

**环境配置**：`.env` 中的 API Key 在两个子系统中共用，迁移时一并配置。

### 9.3 依赖检查清单

| 依赖项 | AI Opinion | 雪球 KB | 备注 |
|--------|:--:|:--:|------|
| DeepSeek API Key | ✅ | ✅ | 共享 |
| GLM API Key | ⚠️ | — | 仅 AI Opinion Vision |
| SQLite DB | ✅ | ✅ | 含 5 张相关表 |
| knowledge/ 目录 | — | ✅ | 38,411 个 .md 文件 |
| prompts/ 目录 | ✅ | — | 2 个模板 |
| stocks 表 | ✅ | — | FK 依赖 |
| journal_entries 表 | ✅ | — | FK 依赖 |

### 9.4 潜在风险

| 风险 | 影响 | 缓解措施 |
|------|------|------|
| 38,411 文件复制遗漏 | 高 | 先 tar/zip 打包再迁移，验证文件计数 |
| 数据库 is_deleted 不一致 | 低 | 迁移后统一加字段（可选） |
| K3 AI 提取结果无法重现 | 中 | 15,122 条已在 DB 中，无需重新提取 |
| K4 HTML 报告路径硬编码 | 低 | 报告自包含，路径相对 |
| KB pipeline 脚本依赖 akshare | 中 | K1/K2 纯本地，K3/K4 需 AI API |

### 9.5 迁移步骤

1. **数据库**：复制 `investment_os.db`，验证 5 张表（ai_opinions 空表 + 4 张雪球表）
2. **文件**：打包 `knowledge/xueqiu/`（~152MB），迁移后验证 38,411 个文件
3. **代码**：复制全部后端文件（18 AI Opinion + 9 雪球 KB）+ 前端 9 文件
4. **配置**：`.env` 中配置 API Key + Provider 参数
5. **验证**：
   - `SELECT COUNT(*) FROM xueqiu_posts_raw` → 38,397
   - `SELECT COUNT(*) FROM knowledge_candidates` → 15,122
   - `POST /ai/reports/daily-summary` → 正常生成
6. **K5 启动**：在新系统中打开 `k4_full_review_report.html`，开始逐条人审确认
