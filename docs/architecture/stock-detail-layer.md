# Stock Detail Layer

## 目标

Stock Detail Layer 用于把单次分析结果、AI 复盘和用户投资日志整合到同一个个股详情入口，形成长期认知档案。

入口页面：

- `apps/dsa-web/src/pages/StockDetailPage.tsx`
- route: `/stocks/:stockCode?market=xxx&recordId=optional`

## 页面信息架构

```text
StockDetailPage
  ├── StockDetailHeader
  ├── CurrentAnalysisCard
  ├── AIOpinionCard
  ├── InvestmentTimeline
  └── AddJournalDialog
```

## 数据依赖

### 当前分析

- `GET /api/v1/history?stock_code=...`
- `GET /api/v1/history/{record_id}`

用途：

- 选择当前展示的 `analysis_history`
- 打开完整报告 drawer

### AI Opinion

- `GET /api/v1/ai-opinions?analysis_history_id=...&current_only=false`
- `POST /api/v1/ai-opinions/generate/{analysis_history_id}`
- `POST /api/v1/ai-opinions/{id}/regenerate`

前端展示逻辑：

- 不只看 current 版本
- 优先展示最新版本，确保 pending/generating 的新版本可见

### Investment Journal

- `GET /api/v1/investment-journals?stock_code=...&market=...`
- `POST /api/v1/investment-journals/manual`
- `POST /api/v1/investment-journals/{id}/structure`
- `POST /api/v1/investment-journals/{id}/retry-structure`

用途：

- 构建 analysis/manual 混合时间线
- 创建手动日志
- 驱动 AI 结构化状态更新

## 状态刷新策略

当前实现不引入 WebSocket，也不引入新的状态框架。

采用：

1. 用户点击触发 AI 动作
2. 后端返回 `202 Accepted`
3. 前端立即写入 pending/processing 状态
4. 前端通过定时刷新重新拉取：
   - AI Opinion 列表
   - Investment Journal 时间线
5. 状态进入终态后停止轮询

终态包括：

- AI Opinion：`completed / failed / rejected`
- Journal structuring：`completed / failed`

## 架构约束

Stock Detail Layer 复用现有 DSA 前端基础设施：

- React
- TypeScript
- axios client
- Zustand
- UiLanguageContext
- 现有 Card / Drawer / Button / EmptyState 等 UI 组件

未新增：

- React Query
- WebSocket
- 新的状态管理框架
- 独立前端 AI client
