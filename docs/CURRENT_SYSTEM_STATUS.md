# 当前项目状态 (CURRENT SYSTEM STATUS)

> **最后更新**: 2026-07-10 | **阶段**: Phase 3 Freeze | **分支**: `investment-os-overlay`
>
> 本文档是 DSA 项目当前唯一状态说明文档。所有后续开发者/协作者应首先阅读本文档以理解系统全貌。

---

## 1. 当前项目定位

**DSA (Daily Stock Analysis) = 个人长期投资认知管理系统**

DSA 是一个面向个人投资者的**认知管理工具**，核心目标是帮助投资者：
- 记录和追踪对个股的每一次分析判断
- 利用 AI 对历史分析进行结构化总结和认知提炼
- 建立长期投资决策的**可追溯记忆**

### DSA 明确不是

| 不是 | 说明 |
|------|------|
| 自动交易系统 | 不会对接券商 API 执行买卖，没有订单管理 |
| 股票推荐机器人 | 不输出「买入」「卖出」建议，不提供投资推荐 |
| 行情终端 | 不提供实时 Level-2 行情、盘口深度、分时图 |
| 量化回测平台 | 不支持策略编写、因子回测、参数优化 |
| 投资组合优化器 | 不提供资产配置建议、组合再平衡 |

### 核心设计哲学

- **认知 > 预测**：记录「我当时怎么看」，而不是「未来会怎样」
- **过程 > 结果**：投资日志的可追溯性比单次分析准确率更重要
- **辅助 > 替代**：AI 是整理和提醒工具，最终决策权始终在用户手中

---

## 2. 当前系统架构

```
┌─────────────────────────────────────────────────────────┐
│                      Frontend                            │
│  apps/dsa-web/ (React + TypeScript + Zustand)            │
│                                                          │
│  ┌──────────────────────────────────────────────┐        │
│  │  StockDetailPage (/stocks/:stockCode)         │        │
│  │  ├─ StockDetailHeader                        │        │
│  │  ├─ CurrentAnalysisCard                      │        │
│  │  ├─ AIOpinionCard                            │        │
│  │  ├─ InvestmentTimeline                       │        │
│  │  └─ AddJournalDialog                         │        │
│  └──────────────────────────────────────────────┘        │
├─────────────────────────────────────────────────────────┤
│                      API Layer                           │
│  api/v1/ (FastAPI)                                       │
│  ├─ endpoints/ai_opinions.py       (AI Opinion CRUD)     │
│  ├─ endpoints/investment_journals.py (Journal CRUD)      │
│  ├─ endpoints/history.py           (分析历史)             │
│  └─ task_queue                     (异步任务队列)         │
├─────────────────────────────────────────────────────────┤
│                    Service Layer                          │
│  src/services/                                            │
│  ├─ ai_opinion_service.py              (业务逻辑)         │
│  ├─ ai_opinion_generation_service.py   (生成编排)         │
│  ├─ ai_opinion_context_builder.py      (上下文构建)       │
│  ├─ ai_opinion_prompt_loader.py        (Prompt 加载)      │
│  ├─ ai_opinion_validator.py            (输出校验)         │
│  ├─ investment_journal_service.py      (日志业务)         │
│  ├─ investment_journal_structuring_service.py (结构化)   │
│  ├─ investment_journal_context_builder.py   (上下文)      │
│  └─ investment_journal_validator.py     (输出校验)        │
├─────────────────────────────────────────────────────────┤
│                   AI Layer (GenerationBackend)            │
│  src/llm/                                                 │
│  ├─ backend_factory.py     (后端工厂)                     │
│  ├─ litellm_backend.py     (LiteLLM 后端)                 │
│  ├─ local_cli_backend.py   (CLI 后端: claude_code/opencode)│
│  └─ hermes/                (Hermes 流式协议)               │
│  src/prompts/              (AI Opinion / Journal Prompts) │
├─────────────────────────────────────────────────────────┤
│                  Repository Layer                         │
│  src/repositories/                                        │
│  ├─ ai_opinion_repo.py           (版本化 AI Opinion)      │
│  └─ investment_journal_repo.py   (投资日志持久化)         │
├─────────────────────────────────────────────────────────┤
│                    Database (SQLite)                       │
│  data/stock_analysis.db                                   │
│  ├─ analysis_history              (每次分析记录)          │
│  ├─ ai_opinions                   (AI 观点，版本化)       │
│  ├─ investment_journal_entries    (投资日志时间线)        │
│  ├─ decision_signals              (决策信号)              │
│  └─ notification_dedup_entries    (通知去重)              │
└─────────────────────────────────────────────────────────┘
```

---

## 3. 当前完整数据流

```
analysis_history (每次分析快照)
        │
        │  手动触发 AI Opinion 生成
        ▼
AI Opinion (对单次分析的结构化认知提取)
  · version 控制，支持 regenerate
  · 状态机: pending → generating → completed / failed / rejected
  · analysis_history 删除后保留，标记 source_status=deleted
        │
        │  按 stock_code + market 聚合
        ▼
Investment Timeline (某只股票的所有投资事件)
  · entry_type: analysis (自动同步) / manual (用户笔记)
  · raw_content 永远不被覆盖
        │
        │  手动触发 AI 结构化
        ▼
Investment Journal (AI 整理的结构化日志)
  · 复用 task_queue + GenerationBackend
  · 结构化结果写入 structured_output_json
  · 失败写入 structured_error
  · 支持 retry
        │
        ▼
AI Structured Memory (长期认知沉淀)
  · summary_snapshot / risk_summary / watch_items
  · 为用户未来决策提供历史参考
```

### 各层说明

| 层 | 作用 | 触发方式 |
|----|------|---------|
| `analysis_history` | 每次 DSA 分析流程的技术面+新闻面原始分析记录 | 自动（每日分析 / 手动分析） |
| `AI Opinion` | 对单次分析的结构化认知解读，提取关键发现、证据、风险、不确定性 | 手动触发（前端按钮） |
| `Investment Timeline` | 按股票聚合的所有分析日志和手动笔记的时间线 | 自动同步 + 手动创建 |
| `Investment Journal` | 手动笔记的 AI 结构化整理，将自由文本转为结构化认知 | 手动触发（前端按钮） |
| `AI Structured Memory` | 长期投资认知的沉淀层，为复盘和原则提取提供数据基础 | 由上层自动产生 |

---

## 4. 已完成阶段

### Phase 1 — 数据基础 (completed)

| 模块 | 内容 |
|------|------|
| `ai_opinions` 数据模型 | 版本化 AI Opinion，关联 `analysis_history`，状态机字段 |
| `investment_journal_entries` 数据模型 | 按 `stock_code + market` 索引，`analysis` / `manual` 双类型 |
| `analysis_history` 关联 | 外键关联，SET NULL on delete，`source_status` 追踪 |
| 投资日志基础 API | CRUD + 分析日志幂等同步 |

### Phase 2 — AI 生成闭环 (completed)

| 模块 | 内容 |
|------|------|
| AI Opinion 生成 | 手动触发 pending → task_queue 异步 → GenerationBackend 生成 → output_json 写入 |
| 状态机 | pending / generating / completed / failed / rejected，含 source_status 追踪 |
| 异步任务队列 | 复用 `task_queue`，`task_id` 格式 `ai_opinion_generate_{id}_{uuid}` |
| GenerationBackend 接入 | LiteLLM + 本地 CLI 后端，含超时、重试、错误映射 |
| Investment Journal 结构化 | 手动 trigger → task_queue → output_json / error 回写 |
| Retry 机制 | AI Opinion regenerate 版本递增，Journal retry-structure 覆盖重试 |
| Prompt 管理 | `src/prompts/` 目录管理，`prompt_loader` 加载，`prompt_version` 追踪 |
| Validator | 输出结构校验，拒绝不合法生成结果 |

### Phase 3 — 前端认知档案页 (completed)

| 模块 | 内容 |
|------|------|
| StockDetailPage | 路由 `/stocks/:stockCode?market=xxx`，单页整合所有认知信息 |
| CurrentAnalysisCard | 展示最近一次分析的技术面/新闻面结论 |
| AIOpinionCard | AI Opinion 版本列表 + generate/regenerate 操作 + 状态轮询 |
| InvestmentTimeline | 按时间排序的 analysis + manual 日志列表 |
| AddJournalDialog | 手动创建投资日志的对话表单 |
| AI 整理交互 | 手动日志的 structure / retry-structure 按钮，轮询刷新状态 |
| 状态刷新 | 无 WebSocket，基于前端轮询 + 202 Accepted 异步模式 |

---

## 5. 当前数据库核心表

### 5.1 `analysis_history`
- 每次 DSA 分析流程的完整快照
- 关键字段: `code`, `name`, `sentiment_score`, `operation_advice`, `trend_prediction`
- 索引: `(code, created_at)` 复合索引

### 5.2 `ai_opinions`
- 关联 `analysis_history_id` (SET NULL on delete)
- 版本化: `version` + `is_current` + UNIQUE `(analysis_history_id, version)`
- 状态: `generation_status` (pending/generating/completed/failed/rejected)
- 内容: `title`, `content`, `conclusion`, `output_json`, `evidence_json`, `risks_json`, `limitations_json`, `watch_items_json`
- 审计: `model`, `provider`, `temperature`, `prompt_version`, `error_message`
- 反馈: `feedback_value`, `feedback_note`, `feedback_updated_at`

### 5.3 `investment_journal_entries`
- 按 `stock_code + market` 索引
- 类型: `entry_type` ∈ {analysis, manual}
- 内容: `raw_content` (永不覆盖), `summary_snapshot`, `risk_summary`, `watch_items_json`
- AI 结构化: `structured_output_json`, `ai_processing_status` (pending/processing/completed/failed)
- 来源追踪: `source_analysis_history_id` (UNIQUE), `source_status`

### 5.4 `decision_signals`
- 决策信号记录，含 action/confidence/score/horizon/价格区间
- 复合索引覆盖 stock_code/market/source/report/status
- 关联: `decision_signal_outcomes` (前瞻结果), `decision_signal_feedback` (用户反馈)

### 5.5 `notification_dedup_entries`
- 通知去重持久化表 (非 ORM，直接 SQLite)
- 支持跨进程互斥，Docker Compose 双服务去重

### 5.6 其他表
- `backtest_results` — 回测结果
- `schema_migrations` — Schema 演进追踪

---

## 6. 当前 API 能力

### AI Opinion API (`/api/v1/ai-opinions`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 按 `analysis_history_id` 查询 AI Opinion 列表 (支持 `current_only`) |
| `/{opinion_id}` | GET | 获取单个 AI Opinion 详情 |
| `/generate/{analysis_history_id}` | POST | 创建 pending AI Opinion 并提交异步生成任务 (202 Accepted) |
| `/{opinion_id}/regenerate` | POST | 为已有 Opinion 创建新版本并重新生成 (202 Accepted) |

### Investment Journal API (`/api/v1/investment-journals`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 按 `stock_code` + `market` + 可选 `entry_type` 查询日志列表 (分页) |
| `/{entry_id}` | GET | 获取单个日志条目 |
| `/manual` | POST | 创建手动投资笔记 |
| `/manual/{entry_id}` | PATCH | 更新手动投资笔记 |
| `/sync-analysis/{analysis_history_id}` | POST | 从分析历史幂等创建分析日志 (幂等) |
| `/{entry_id}/structure` | POST | 提交日志 AI 结构化任务 (202 Accepted) |
| `/{entry_id}/retry-structure` | POST | 重试日志 AI 结构化 (202 Accepted) |

---

## 7. 明确未开发功能

以下功能**不在当前系统范围内**，不应在后续开发中被误认为是缺失功能：

| 未开发功能 | 说明 |
|-----------|------|
| 自动交易 | 不对接券商 API，不执行买卖订单 |
| 自动买卖建议 | 不输出买入/卖出/持有建议 |
| 投资组合优化 | 不提供马科维茨优化、风险平价等 |
| 多模型协同 | 不同时调用多个模型对同一标的分析 |
| 新闻推荐系统 | 不主动推送资讯，不基于用户画像推荐 |
| 自动投资决策 | 不代替用户做任何投资决策 |
| 实时行情推送 | 不提供 WebSocket 实时行情 |
| 策略回测引擎 | 不支持自定义策略编写和回测 |
| 社交/分享功能 | 不支持报告分享、社区讨论 |
| 知识库接入 | AI Opinion 不接入外部知识库/RAG |
| 独立的 Opinion/Journal 页面 | 目前仅在 StockDetailPage 中嵌入展示 |

---

## 8. 下一阶段方向（规划，不开发）

### Phase M — 投资原则库

**目标**: 从历史投资日志和 AI Opinion 中提取用户的投资原则，建立纪律检查机制。

#### 投资原则提取
- 从 `investment_journal_entries` 的结构化输出中提取反复出现的决策模式
- 识别用户的买入/卖出/持有逻辑偏好
- 建立用户专属投资理念档案

#### 大 V 理念库
- 录入经典投资理念 (如巴菲特、芒格、彼得林奇等)
- 与用户自身原则对比，发现一致与冲突

#### 投资纪律
- 定义可检查的投资规则 (如：不在下跌趋势中补仓、单只股票仓位上限)
- AI 监督：检查投资行为是否违反已定义的原则
- 复盘提醒：在复盘时提示与原则不一致的决策

### AI 监督
- 基于已提取的投资原则，对新的分析/操作进行合规检查
- 复盘时自动标记与原则不一致的决策
- 提供「投资纪律报告」，辅助用户反思

> **注意**: 以上仅为规划方向，当前阶段**不进行任何代码开发**。

---

## 附录：关键文件索引

| 文件 | 说明 |
|------|------|
| `docs/AI_OPINION_AND_INVESTMENT_JOURNAL_GUIDE.md` | AI Opinion 和 Investment Journal 功能指南 |
| `docs/architecture/stock-detail-layer.md` | StockDetailPage 前端架构文档 |
| `docs/CHANGELOG.md` | 版本变更日志 |
| `AGENTS.md` | 开发协作规范 |
| `api/v1/endpoints/ai_opinions.py` | AI Opinion API 端点 |
| `api/v1/endpoints/investment_journals.py` | Investment Journal API 端点 |
| `src/storage.py` | 数据库模型定义 |
| `apps/dsa-web/src/pages/StockDetailPage.tsx` | 股票详情页主组件 |
