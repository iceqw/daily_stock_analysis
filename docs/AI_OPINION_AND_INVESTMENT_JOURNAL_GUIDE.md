# AI Opinion 与 Investment Journal 使用指南

## 1. AI Opinion 是什么

AI Opinion 是基于单次 `analysis_history` 生成的研究复盘摘要。它的目标不是给出交易建议，而是把已有分析中的关键信息重新整理为：

- summary
- key findings
- supporting evidence
- risks
- uncertainties
- limitations
- things to watch
- investment discipline notes
- disclaimer

AI Opinion 只允许手动触发，不会在每次分析后自动消耗模型额度。

## 2. Investment Journal 是什么

Investment Journal 是围绕个股形成的长期投资日志时间线，包含两类条目：

- analysis：由 `analysis_history` 同步而来的自动分析记录
- manual：用户手动录入的投资笔记

手动笔记的 `raw_content` 永远保留，AI 结构化只会把内容整理到 `structured_output_json`，不会覆盖原文。

## 3. 两者区别

AI Opinion 和 Investment Journal 的边界不同：

- AI Opinion：围绕一次分析结果做 AI 复盘
- Investment Journal：围绕一只股票沉淀长期研究和复盘记录

AI Opinion 属于历史研究资产。即使来源 `analysis_history` 被删除，已生成的 AI Opinion 仍会保留，并标记来源不可用。

## 4. 前端使用流程

当前 Web 入口为：

- `/stocks/:stockCode?market=xxx`

页面包含三个主要区域：

1. 当前分析
   - 展示最新 `analysis_history`
   - 支持打开完整报告

2. AI Opinion
   - 展示最新 AI Opinion 版本
   - 支持手动生成和重新生成
   - 状态支持 `pending / generating / completed / failed / rejected`

3. Investment Timeline
   - 倒序展示 analysis 与 manual 两类日志
   - 支持新增手动投资日志
   - 支持对 manual 条目触发 AI 整理与重试

## 5. AI 安全边界

### AI Opinion

AI Opinion 明确限制为研究整理能力，不允许：

- 买入建议
- 卖出建议
- 加仓建议
- 减仓建议
- 确定性收益或涨跌预测

### Investment Journal 结构化

Investment Journal AI 结构化只允许整理用户原文，不允许补充外部事实，不允许把用户过去写下的“打算买入”转换成系统建议语气。

### Prompt Injection

用户日志中的内容被视为不可信输入：

- 不进入 system prompt
- 不能覆盖系统安全指令
- 只能作为待整理文本处理

## 6. 当前页面能力范围

Phase 3 当前完成的是前端集成，不包含：

- 独立 AI Opinion 页面
- 独立 Journal 页面
- 知识库接入
- WebSocket 实时推送

页面采用轮询刷新：用户触发 AI 动作后，前端会短周期刷新 AI Opinion 与 Investment Timeline，直到状态进入终态。
