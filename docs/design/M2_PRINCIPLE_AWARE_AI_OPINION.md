# M2-1：原则感知 AI Opinion 设计与数据契约

状态：待审查

本文档只定义 M-2 的设计与数据契约，不包含生产代码、数据库迁移、API 实现、前端实现或 LLM 调用。

## 0. 审计基线与适用范围

本设计基于以下两类证据：

1. `origin/main` 当前基线 `627d361a952c0492c4d4e584252559f75e99e26b` 的现有代码、测试和文档。
2. 当前基线历史中可审阅但不属于当前树的 M-1/AI Opinion 实现提交：`32a34e7`（M-1 投资原则库）及其祖先链中的 `562a492`、`bf4eff1`、`adfe6ff` 等 AI Opinion 提交。

审计发现：当前 `origin/main` 的工作树不包含 `investment_principles`、`ai_opinions`、M-1 Repository/Service/API 文件；这些文件存在于上述历史提交，但 `32a34e7` 不是当前 `main` 的祖先。因此，本文把历史实现作为已存在设计的审阅材料，不把它误写成当前 `origin/main` 已部署的运行时契约。后续实现前必须先确认 M-1/AI Opinion 代码将以何种方式回到目标基线。

当前基线中可直接确认的数据库约定是：SQLite/SQLAlchemy ORM 位于 `src/storage.py`，通过 `Base.metadata.create_all()` 建表，并用 `schema_migrations` 记录 `CURRENT_SCHEMA_VERSION`；当前主线的 `analysis_history` 包含 `context_snapshot` 等历史分析字段。历史 M-1 实现的 schema marker 为 `2026-07-13-investment-principles-m1`。

## M2-0：恢复并验收 M-1 / AI Opinion 基线

M2-0 是所有后续 M-2 实现的前置阶段，且是 M2-2 的直接前置依赖。目标不是在本轮恢复代码，而是先把历史 M-1 / AI Opinion 实现恢复到目标分支，再完成基线验收：原则库表、版本/状态转换、Repository/Service/API、`ai_opinions` 版本状态机、后台生成、retry/regenerate、Prompt、Schema、Validator 和相关测试必须在同一可运行基线上一致。

验收至少包括：当前分支包含实际运行时代码和迁移/建表约定；M-1 原则查询能返回 active/current 版本；AI Opinion 生成、失败、拒绝、retry、regenerate 和历史查询测试通过；`generation_status` 的 Service 与 API Schema 合法集合统一；并确认本设计中的 `principle_snapshot_json`、refs 两阶段写入和删除语义能够落到真实 ORM/事务边界。M2-0 未完成时，不开始 M2-2，也不以历史提交本身替代当前基线验收。

## 1. 背景与问题

历史 AI Opinion 实现已经围绕 `analysis_history` 提供版本化 Opinion、异步生成、失败/拒绝状态、重试计数、上下文 hash、Prompt 版本和审计元数据。历史实现中的 `AIOpinionRecord` 已有 `output_json`、`prompt_version`、`audit_metadata_json`、`context_hash`、`retry_count` 等字段；生成链路使用 `AnalysisOpinionContextBuilder`、Prompt loader、共享 `GenerationBackend` 和 `ai_opinion_validator`。

但现有 Opinion 没有绑定某次生成所使用的正式投资原则。缺少原则引用会导致：

- 纪律判断无法追溯到具体原则和版本；
- 原则修改或停用后，历史 Opinion 难以证明当时依据；
- 模型可能虚构原则 ID、混用旧版本或把原则正文改写成交易命令；
- 用户无法知道某条 Opinion 使用了哪些原则、证据和判断理由。

M-2 的目标是让每条 Opinion 保存可复现的原则快照及逐条结构化评估，而不是生成买卖建议。

## 2. 目标、非目标与第一版边界

### 2.1 目标

- 生成开始时只读取“已启用且当前有效版本”的正式原则。
- 在任务启动时冻结原则集合、完整规范化载荷、版本、必要元数据和内容 hash。
- 把冻结集合传给 Context/Prompt，并校验模型只能引用白名单中的原则。
- 保存原则引用、标题快照、完整规范化载荷、内容 hash 和逐条评估。
- 使原则后续修改、停用或删除不影响历史 Opinion 的可审计性。
- 明确首次生成、失败重试和主动重新生成的版本语义。
- 定义 API、Schema、校验失败状态、事务边界和最小前端展示契约。

### 2.2 非目标

本阶段不实现自动买卖建议、自动下单、交易阻断、自动修改正式原则、雪球帖子直接入正式原则、批量重算历史 Opinion、完整 RuleEngine、用户自定义系统 Prompt、自动调度、前端代码、生产代码或数据库迁移。

硬性原则被模型评估为 `violated` 时只记录审查结果，不阻止交易，也不生成自动执行命令。

## 3. 当前实现审计摘要

历史 M-1 真实模型为：

- `investment_principles`：稳定原则身份、`status`、`current_version` 及生命周期时间字段；状态约束为 `draft`、`active`、`archived`、`rejected`。
- `investment_principle_versions`：不可变版本内容，包含 `principle_id`、`version`、`title`、`statement`、`rationale`、`category`、`severity`、scope 和 `change_note`；`(principle_id, version)` 唯一。
- `investment_principle_sources`：版本来源及来源状态，不能把来源记录当作正式原则本身。
- 历史 Repository 提供 `get_current_version`、`create_next_version`、状态转换和 `list_current`；版本更新和状态变更使用事务及乐观并发条件。

历史 AI Opinion 真实模型为 `ai_opinions`：

- `analysis_history_id` 外键为 `SET NULL`，`version` 与 `analysis_history_id` 唯一；`is_current` 标记当前版本。历史实现的状态语义须在 M2-0 统一。
- `generation_status` 的 ORM 默认值为 `pending`；历史 Service 允许 `pending`、`failed`、`rejected`，历史 API Schema 还声明 `generating`、`completed`，因此 M2 实现前必须统一这处现有状态契约。
- `source_status` 为 `available`/`deleted`。
- 已有 `output_json`、`prompt_version`、`audit_metadata_json`、`context_hash`、`retry_count`，没有原则引用表或原则快照字段。

历史生成接口为 `/api/v1/ai-opinions` 路由组：列表、详情、`POST /generate/{analysis_history_id}`、`POST /{opinion_id}/regenerate` 和反馈接口。首次生成先创建 pending Opinion，再提交后台任务；主动重新生成创建新的 Opinion 版本。历史生成器通过共享 `GenerationBackend` 调用模型，Schema 解析失败进入 `failed`，安全禁止内容进入 `rejected`，其他异常进入 `failed`。

历史 `AIOpinionStructuredOutput` 使用 `ai-opinion-output-v1`，已有 `summary`、`key_findings`、`supporting_evidence`、`risks`、`uncertainties`、`limitations`、`things_to_watch`、`investment_discipline_notes`、置信度和 disclaimer。证据引用有 `source_type`/`source_ref` 白名单校验，已有买卖、目标价、止损等禁止模式。

## 4. 核心业务流程

```text
analysis_history
  → 读取正式、active、current 原则
  → PrincipleContextBuilder 规范化、排序、限额并冻结快照
  → 保存任务级 snapshot metadata
  → 组合 Analysis Opinion Context + Principle Context
  → 调用现有 GenerationBackend
  → 解析并校验结构化 JSON
  → 在同一写事务中保存 Opinion 与 principle refs
  → 返回 Opinion 及原则评估
```

### 4.1 首次生成

创建 pending Opinion 时立即读取原则并冻结快照，不能把读取推迟到后台任务实际执行时。后台任务只消费已冻结的 snapshot。新建 Opinion 即使原则集合为空，也必须保存规范化空数组 `[]` 及其确定性 `principle_snapshot_hash`，不能写 null；只有无法回填快照的历史数据允许 hash/json 为 null。原则读取失败则任务失败，不得静默当作无原则。

原则引用分两阶段写入：

1. `pending` 创建时保存本次完整规范化快照、snapshot hash/count，并为每条冻结且保留的原则创建一条 ref；assessment 字段暂允许为 null。
2. 生成完成并通过校验时，补齐每条 ref 的 assessment 字段。`completed` 的 Opinion 中，每条冻结且保留的原则必须有且仅有一个 assessment，不能缺项、重复或只保存在模型输出 JSON 中。

### 4.2 失败重试

retry 必须复用首次启动时冻结的原则快照、排序和 snapshot hash，不重新查询 active/current 原则。若快照无法读取或校验不一致，任务进入 `failed` 并保留错误审计信息。重试不会创建新的 Opinion 版本；只更新同一 pending/failed 记录的 retry 状态，具体次数沿用现有 `retry_count` 语义。

### 4.3 主动重新生成

用户主动重新生成时创建新的 Opinion 版本，重新读取当时最新的 active/current 原则并创建新的冻结快照。旧 Opinion 和旧 refs 不更新、不删除、不重新计算。新版本成功后才成为 `is_current=true`；失败版本保留失败状态，不应把旧成功版本标记为不可用。

### 4.4 原则修改、停用与删除

原则新版本写入或状态变更不触发历史 Opinion 重算。历史 refs 保存当时的 ID、版本、标题、完整规范化载荷和内容 hash，因此原则被 archived、rejected 或物理删除后仍可显示引用。Opinion 被删除时 refs 随 Opinion 删除；推荐 `ai_opinion_id ON DELETE CASCADE`。原则生命周期变化不得删除 refs，`principle_id` 只作为快照身份值，不作为必须存活的级联外键。正式原则实体删除应优先禁止，或只允许软生命周期变更。

## 5. 数据模型设计

### 5.1 方案比较

| 方案 | 优点 | 缺点 | 结论 |
| --- | --- | --- | --- |
| 全部放 `audit_metadata_json` | 初期改动少 | 无法约束唯一引用、难查询、难分页和统计，字段契约不稳定 | 不采用 |
| 独立 `ai_opinion_principle_refs` | 可审计、可索引、可逐条返回、可约束重复评估 | 需要新增表及事务写入 | 采用为主方案 |
| 独立表 + Opinion 汇总字段 | 兼顾详情查询和列表性能 | 有少量冗余，需定义一致性 | 采用混合方案 |

### 5.2 `ai_opinion_principle_refs` 推荐契约

推荐新增独立关联表，字段如下。类型按当前 SQLAlchemy/SQLite 风格表达，最终以实现时的 ORM 命名为准。

| 字段 | 类型 | nullable | 说明 |
| --- | --- | --- | --- |
| `id` | Integer PK | 否 | 自增主键 |
| `ai_opinion_id` | Integer FK `ai_opinions.id` | 否 | `ON DELETE CASCADE`，Opinion 删除时删除 refs |
| `principle_id` | Integer | 否 | 原则稳定身份值；不建立会影响历史审计的级联外键 |
| `principle_version` | Integer | 否 | 生成时的不可变版本号 |
| `category` | String(64) | 否 | 沿用 M-1 的真实分类字段 |
| `severity` | String(16) | 否 | 沿用 M-1 的真实严重程度字段 |
| `principle_title_snapshot` | String(200) | 否 | 标题快照，避免历史展示依赖当前原则 |
| `principle_snapshot_json` | Text | 否（pending 起） | 完整规范化原则载荷，供 retry 重建相同 Context；不是只读的当前原则查询结果 |
| `principle_content_hash` | String(64) | 否 | 规范化正文 hash；至少覆盖 `statement`，推荐覆盖用于 Prompt 的完整规范化内容 |
| `assessment_status` | String(32) | 是（completed 前） | 五种固定状态之一；pending 阶段为 null |
| `relevance` | Float | 是（completed 前） | `[0, 1]`；completed 时必填 |
| `evidence_json` | Text | 是（completed 前） | 结构化证据数组；completed 时为数组，默认 `[]` |
| `explanation` | Text | 是（completed 前） | 逐条判断说明；completed 时必填，`not_applicable` 也说明原因 |
| `confidence` | Float | 是（completed 前） | `[0, 1]`；completed 时必填 |
| `created_at` | DateTime | 否 | 引用写入时间 |

唯一约束推荐为 `(ai_opinion_id, principle_id, principle_version)`；由于一次冻结集合中同一原则 ID 只能有一个版本，实际 validator 还必须拒绝同一 Opinion 中重复 `principle_id`。索引为 `(ai_opinion_id, created_at, id)` 和 `(principle_id, principle_version)`。`principle_snapshot_json` 必须从 pending 起保存，不能只保存标题和 hash；它是 retry 的完整规范化输入，refs 中的快照字段必须与之可校验一致。

### 5.3 `ai_opinions` 汇总字段

推荐增加：

- `principle_snapshot_hash`：本次冻结集合的确定性 hash；新建 Opinion 即使集合为空也必须非空，只有历史数据允许 null。
- `principle_snapshot_count`：冻结集合总数，默认 0。

不推荐增加 `principles_applied` 作为第二个原则列表真源；逐条引用表和 `principle_snapshot_json` 是本次生成的审计输入来源，列表接口可按 refs 聚合。`audit_metadata_json` 仅保存 builder 版本、截断计数、排序算法版本、读取时间和错误码等诊断信息，不替代完整快照。

### 5.4 快照 hash 与内容规范化

对每条原则构造规范化对象：`principle_id`、`principle_version`、`category/type`、`severity`、scope、`title`、`statement`、必要 `rationale`。文本统一 Unicode NFC、换行符为 `\\n`、去除首尾空白；JSON 使用 UTF-8、固定字段顺序、无多余空白。先对每条规范化对象计算 `content_hash=SHA-256(canonical_json)`，再按确定性排序后把完整对象数组计算 `principle_snapshot_hash`。同一输入、同一 builder/schema 版本必须得到同一 hash。

## 6. 原则评估状态

状态固定为：

| 状态 | 严格含义 | 边界 |
| --- | --- | --- |
| `aligned` | 当前分析提供了足够证据，且没有识别到与原则冲突的行为或结论 | 不是“模型赞同原则”，而是分析证据与原则要求一致 |
| `at_risk` | 存在可能偏离原则的信号、条件或未解决风险，但证据不足以断言违反 | 风险不等于违反；必须写解释和证据/缺口 |
| `violated` | 当前分析中的事实、行为或结论与原则要求存在明确冲突 | 必须有至少一条合法白名单证据；只记录，不阻断交易 |
| `not_applicable` | 原则的 scope、资产类型、市场或当前问题不适用于本次分析 | 不计入总体纪律分母，不降低总体纪律评分 |
| `insufficient_evidence` | 原则适用或可能适用，但输入不足以可靠判定 | 不得写成 `violated`；应列出缺失证据 |

`at_risk`、`violated` 必须有非空 `explanation`。`violated` 必须有至少一条合法白名单证据；证据不足只能使用 `insufficient_evidence`，不得把证据不足的判断标记为 `violated`。硬性原则的 `violated` 只形成审计记录。

## 7. PrincipleContextBuilder

建议新增设计组件 `PrincipleContextBuilder`，职责仅限于读取和纯计算：

- 查询正式原则的当前版本，条件必须同时满足 `InvestmentPrinciple.status='active'`、版本等于 `current_version`，并满足 scope；
- 输出模型所需的最小字段，不输出内部配置、密钥、来源敏感信息或可编辑 Prompt；
- 按确定性顺序排序；当前 M-1 可用字段的推荐顺序为 `severity` → `category` → `principle_id` → `version`，不提前引入没有真实字段支持的 `priority` 或 `principle_type`；
- 控制最大原则数量、单条文本长度和总 token 预算；
- 生成 canonical snapshot、snapshot hash、计数和截断统计；
- 不调用 LLM、不修改原则、不写数据库。

原则过多时默认优先保留硬性/高严重程度原则，再按稳定排序截断普通原则；不得静默截断。被截断数量、保留数量、总数、上限和 builder 版本写入审计元数据。第一版建议超出硬性上限时任务 `failed`，或在产品明确允许时显式 `truncated=true` 后继续；不能在用户不可见的情况下静默丢失原则。

## 8. AI 输出 JSON Schema

Schema 版本建议为 `ai-opinion-output-v2`，保留现有 v1 字段名，新增原则相关字段，避免把已有 `supporting_evidence`、`things_to_watch` 等字段改名：

```json
{
  "schema_version": "ai-opinion-output-v2",
  "summary": "",
  "key_findings": [],
  "supporting_evidence": [],
  "risks": [],
  "uncertainties": [],
  "limitations": [],
  "things_to_watch": [],
  "investment_discipline_notes": [],
  "principle_assessment": [],
  "overall_discipline_summary": "",
  "confidence": {"level": "low", "rationale": ""},
  "disclaimer": ""
}
```

`schema_version`、`summary`、`key_findings`、`supporting_evidence`、`risks`、`uncertainties`、`limitations`、`things_to_watch`、`investment_discipline_notes`、`principle_assessment`、`overall_discipline_summary`、`confidence`、`disclaimer` 为 required；数组不得为 null，空集合使用 `[]`。沿用当前字符串长度和数组上限，新增 `principle_assessment` 最多等于冻结且保留原则数且不超过实现配置上限。第一版不输出独立 `principle_conflicts` 模型字段；冲突从逐条 assessment 中 `violated`/`at_risk` 的结果推导。

每个 assessment 必须包含：

```json
{
  "principle_id": 1,
  "principle_version": 2,
  "status": "aligned",
  "relevance": 0.0,
  "evidence": [],
  "explanation": "",
  "confidence": 0.0
}
```

`principle_id` 和 `principle_version` 为正整数；`status` 只能取五种固定值；`relevance` 和 assessment `confidence` 均为 `[0,1]`；`evidence` 使用现有证据引用格式，推荐每项包含 `statement`、`source_type`、`source_ref`，且 `source_ref` 必须来自本次 context 白名单。`violated` 必须有至少一条合法证据，`violated`/`at_risk` 的 explanation 非空。空原则集合时 `principle_assessment=[]`、`overall_discipline_summary` 明确写“本次无有效原则可评估”，不伪造原则。

当前 v1 的置信度是离散 `low|medium|medium_high`；M2 新增逐条数值 confidence 时，保留总体 v1 字段以兼容现有客户端，并在 v2 中明确两者语义：总体 confidence 仍为既有对象，逐条 confidence 为 `[0,1]`。实现前需确认是否接受这一双层表示。

## 9. Validator 设计

在已有 JSON 解析和禁止交易建议校验之后，新增原则校验：

1. `principle_id` 必须属于冻结白名单。
2. `principle_version` 必须与白名单快照完全一致。
3. 同一 Opinion 不得重复评估同一 `principle_id`。
4. status、confidence、relevance 必须合法。
5. 不允许模型输出未请求的原则、修改原则正文或伪造原则元数据。
6. `at_risk`、`violated` 必须有 explanation；`violated` 必须有至少一条合法白名单证据，证据不足必须使用 `insufficient_evidence`。
7. 检查所有文本，拒绝买入、卖出、加仓、减仓、目标价、止损、自动执行等指令性表达。
8. 检查原则评估不能被写成自动执行命令。

状态统一规则：无法解析 JSON、网络失败、上下文/快照读取失败、持久化失败进入 `failed`；JSON 可解析但白名单、版本、状态或安全契约违规进入 `rejected`。这里需要在 M2-0 统一历史 Service 与 API Schema 当前对 `completed/generating` 的差异；推荐状态机为 `pending → generating → completed|failed|rejected`。

## 10. API 契约

沿用已有 `/api/v1/ai-opinions` 路由组，不创建重复生成 Endpoint。

### 10.1 生成与重试

- `POST /api/v1/ai-opinions/generate/{analysis_history_id}`：创建 pending Opinion 并冻结 active/current 原则；第一版不暴露 `use_active_principles` 请求开关。响应继续返回 Opinion、task/trace 信息，同时包含 snapshot hash/count。
- `POST /api/v1/ai-opinions/{opinion_id}/regenerate`：不接受任意原则 ID；创建新版本并使用请求时最新 active/current 原则。
- retry 复用服务端冻结快照，客户端不能通过重试切换原则。
- 第一版不支持关闭原则读取/检查的开关；无原则是合法的空集合，原则读取失败不是空集合。

### 10.2 查询

现有 `GET /api/v1/ai-opinions/{opinion_id}` 和列表响应增加兼容的原则汇总/评估字段，历史 Opinion 从 refs 返回其原始快照。若详情载荷不宜增大，增加只读接口：

`GET /api/v1/ai-opinions/{opinion_id}/principles`

响应示例：

```json
{
  "opinion_id": 42,
  "principle_snapshot_hash": "sha256:…",
  "principle_snapshot_count": 2,
  "items": [
    {
      "principle_id": 7,
      "principle_version": 3,
      "principle_title_snapshot": "风险暴露需有证据",
      "category": "risk_management",
      "severity": "hard",
      "assessment_status": "at_risk",
      "relevance": 0.8,
      "evidence": [],
      "explanation": "输入包含风险信号，但缺少仓位信息。",
      "confidence": 0.62
    }
  ]
}
```

错误码建议沿用现有风格：`404 not_found`（Opinion 不存在）、`409 conflict`（版本/并发冲突）、`422 context_unavailable`（分析历史或冻结快照不可用）、`400 validation_error`（请求参数非法）、`500 internal_error`（未分类持久化/基础设施错误）。原则读取失败、snapshot 校验失败和事务失败必须保留服务端审计错误码，不泄漏 Prompt 或密钥。历史 Opinion 查询必须返回其原始 snapshot 信息，即使当前原则已停用。

## 11. 前端最小展示契约（只设计）

在 Opinion 详情增加“投资原则检查”区域，逐条显示标题、版本、类型、严重程度、状态、证据、解释和置信度。状态映射：`aligned=符合`、`at_risk=存在风险`、`violated=疑似违反`、`insufficient_evidence=证据不足`、`not_applicable=不适用`。空原则显示“本次无有效原则可评估”；不设计复杂图表、统计大盘或自动提醒。

## 12. 事务、幂等与一致性

- pending Opinion 创建、版本号分配、完整 `principle_snapshot_json`、snapshot hash/count 和 refs 初始行应在同一数据库事务中完成；不能先提交 Opinion 再无保护地写 refs。
- 生成结果补写 Opinion 与 refs assessment 也应同一事务。任一 refs 写入失败，整体回滚到生成前状态，并将持久化错误记录为 `failed`；不要留下“completed 但无 refs”或“completed 缺 assessment”的半成品。
- `ai_opinion_principle_refs` 的唯一约束防止重复引用；validator 防止同一原则重复评估。Opinion 删除时通过 `ON DELETE CASCADE` 删除 refs，原则生命周期变化不删除 refs。
- 现有 `(analysis_history_id, version)` 唯一约束继续负责版本分配；并发生成遇到冲突返回 `409` 或按现有服务语义转换为冲突，不静默覆盖。
- 主动重新生成和 retry 分离：retry 不产生新 version；regenerate 产生新 version 和新 snapshot。
- 当前原则版本切换与生成快照读取必须在同一读取事务/一致性边界内完成，避免读到身份表的新 `current_version` 与旧版本正文的混合结果。

## 13. 隐私、安全与 Prompt 边界

只把模型判断必需的原则 ID、版本、类型、严重程度、scope、标题和规范化正文传入 Context。不得传入 API key、内部配置、用户密钥或不必要的来源全文。系统 Prompt 仍由服务端管理，用户不能编辑。原则正文属于用户数据；日志只记录 ID、版本、hash、计数和错误码，不完整记录敏感正文。API 错误不得泄漏 Prompt、模型原始响应或密钥。AI 输出仅用于辅助审查，不构成投资建议，也不执行或阻止交易。

## 14. 测试计划

后续实现至少覆盖：

- 只读取 active/current 原则；scope 过滤正确；
- severity/category/id/version 排序稳定；同输入得到同 content hash/snapshot hash；
- 原则更新后旧 Opinion 和 refs 不变；主动重新生成使用新版本；retry 使用冻结快照；
- 原则停用/删除后历史 refs 仍可查；无原则时正常生成且保存空数组 snapshot/hash；原则读取失败时任务 `failed`；
- 虚构 ID、错误 version、非法 status、重复评估被 `rejected`；
- `violated` 缺合法证据、`violated`/`at_risk` 缺 explanation 被拒绝；交易建议输出被拒绝；
- Opinion 与 refs 同事务回滚；并发版本冲突和重复请求幂等；
- API 返回 snapshot/hash/count 和历史审计信息；
- 前端五种状态映射及空集合展示。

## 15. 后续实施任务拆分

### M2-0 Baseline Restoration

- 目标：恢复并验收 M-1 / AI Opinion 代码、Schema、状态机、迁移/建表约定和测试基线。
- 文件候选：历史实现对应的 `src/storage.py`、`src/repositories/`、`src/services/`、`api/v1/`、Prompt、测试和 `docs/migration/`；以目标分支实际树为准。
- 依赖：目标基线确认及历史实现审阅。
- 验收：M-1 active/current 查询、AI Opinion 首次生成/失败/retry/regenerate/历史查询和状态契约均可运行；确认 `principle_snapshot_json`、两阶段 refs 和删除语义的实现落点。
- 不做：M2-2 及任何原则感知生成逻辑。

### M2-1 Design Contract

- 目标：冻结本设计中的数据、状态、Schema、Validator、API、事务和安全契约。
- 文件候选：`docs/design/M2_PRINCIPLE_AWARE_AI_OPINION.md`。
- 依赖：M2-0 的基线审计结果。
- 验收：设计与 M2-0 真实字段/状态/路由一致，评审确认快照、refs 两阶段写入和错误状态语义。
- 不做：生产代码、迁移、Prompt、测试和前端实现。

### M2-2 PrincipleContextBuilder

- 目标：读取 active/current 正式原则，稳定排序、限额、规范化并生成 snapshot/hash。
- 文件候选：`src/services/`、`src/repositories/investment_principle_repo.py`、相关单测。
- 依赖：M2-0 基线恢复验收、M2-1 设计契约。
- 验收：只读正确版本、hash 可复现、截断显式、无数据库写入/LLM 调用。
- 不做：Prompt、Schema、API、迁移和交易规则引擎。

### M2-3 Prompt / Schema / Validator

- 目标：在现有 v1 Opinion 输出上兼容扩展 v2 原则评估并完成白名单和安全校验。
- 文件候选：`src/prompts/ai_opinion/`、`src/services/ai_opinion_validator.py`、API Schema。
- 依赖：M2-1 设计契约、M2-2 的冻结快照契约。
- 验收：非法 ID/version/status、重复评估、缺证据/解释、交易命令均拒绝。
- 不做：生成服务接线、持久化和前端。

### M2-4 Generation Service / Persistence

- 目标：把冻结快照接入首次生成、retry、regenerate，并原子保存 Opinion 与 refs。
- 文件候选：`src/storage.py`、`src/repositories/ai_opinion_repo.py`、`src/services/ai_opinion_generation_service.py`、迁移文件（后续阶段）。
- 依赖：M2-0、M2-2、M2-3 及状态机统一决策。
- 验收：旧版本不变、retry 不换快照、refs 事务一致、并发冲突可解释。
- 不做：API 路由、Web UI、自动交易阻断。

### M2-5 API / Web UI

- 目标：扩展现有 Opinion 生成/查询契约，提供原则评估详情和最小状态展示。
- 文件候选：`api/v1/endpoints/ai_opinions.py`、`api/v1/schemas/ai_opinions.py`、`apps/dsa-web/src/api/aiOpinions.ts`、Opinion 组件。
- 依赖：M2-0、M2-4 持久化字段和响应结构。
- 验收：生成、retry、regenerate、历史查询和五种状态展示一致。
- 不做：复杂图表、自动提醒、交易阻断。

### M2-6 Tests / Documentation / Acceptance

- 目标：补齐契约测试、迁移验证、API/Web 验收和用户文档。
- 文件候选：相关 `tests/test_ai_opinion_*.py`、原则测试、API/Web 测试、`docs/` 专题文档。
- 依赖：M2-0 至 M2-5。
- 验收：本节测试计划全部有证据，CI/本地结果与 PR 描述一致。
- 不做：扩大范围到自动调度、RuleEngine 或批量历史重算。

## 16. 风险与待确认事项

只保留代码审计后仍未确定的技术问题：

1. 当前 `origin/main` 缺少历史 M-1/AI Opinion 文件；需确认恢复这些实现的目标分支/合并方式和最终基线。
2. 历史 AI Opinion Service 与 API Schema 对 `generation_status` 的合法集合不一致，需统一 `generating`、`completed` 的状态机定义。
3. M-1 当前字段有 `category`/`severity`，没有审计要求中的独立 `principle_type`/`priority`；需确认 M2 映射和硬性规则合法值。
4. 当前数据库主要使用 `create_all` 加 schema marker 和局部修复函数；M2 需要确认正式迁移脚本机制、SQLite 旧表升级方式和回滚策略。
5. 需要确认 API 是否直接扩展详情响应，还是采用独立 `/principles` 详情接口，以控制历史 Opinion 载荷大小。
6. 需要确认原则正文是否属于必须可离线展示的审计材料；本文默认只保存标题和 hash，正文不重复保存。
7. 需要确认同一分析历史允许多个并发 pending 任务时，现有 `has_inflight_generation` 语义是否足以覆盖 snapshot 冻结幂等。

## 17. Definition of Done

M-2 完成后，每条 AI Opinion 必须能够回答：

```text
使用了哪些原则？
使用了哪个原则版本？
原则快照和 hash 是否可复现？
每条原则的判断状态是什么？
证据和解释是什么？
是否存在冲突或证据不足？
为什么旧 Opinion 不受新原则影响？
```

达到这些条件的前提是：原则引用与 Opinion 同事务保存，retry 使用启动时快照，regenerate 创建新版本，历史 refs 不因原则生命周期变化而丢失，并且模型输出不能越过白名单和安全校验。
