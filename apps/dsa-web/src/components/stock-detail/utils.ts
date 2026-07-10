import type { UiLanguage } from '../../i18n/uiText';
import { normalizeStockCode } from '../../utils/stockCode';

const STOCK_DETAIL_TEXT = {
  zh: {
    archiveTitle: '股票长期认知档案',
    archiveSubtitle: '整合当前分析、AI 复盘与投资日志，形成长期时间线。',
    currentAnalysis: '当前分析',
    currentAnalysisSubtitle: 'latest analysis history',
    noCurrentAnalysis: '暂无分析记录',
    noCurrentAnalysisDescription: '当前股票还没有 analysis history，可先完成一次分析后再查看 AI 复盘与时间线。',
    openFullReport: '查看完整报告',
    analysisSummary: '分析摘要',
    reportType: '分析类型',
    generatedAt: '生成时间',
    model: '模型',
    version: '版本',
    promptVersion: 'Prompt 版本',
    aiOpinion: 'AI Opinion',
    aiOpinionSubtitle: 'research recap',
    generateOpinion: '生成 AI 复盘',
    regenerateOpinion: '重新生成',
    noOpinion: '暂无 AI 复盘',
    noOpinionDescription: 'AI Opinion 不会自动生成，需要手动触发。',
    opinionPending: 'AI Opinion 已进入队列，正在等待执行。',
    opinionGenerating: 'AI Opinion 正在生成。',
    opinionFailed: 'AI Opinion 生成失败。',
    opinionRejected: 'AI Opinion 因安全规则被拒绝。',
    sourceDeleted: '来源分析已删除，当前仅保留历史 AI 复盘资产。',
    summary: '摘要',
    keyFindings: '关键发现',
    supportingEvidence: '支持证据',
    risks: '风险',
    uncertainties: '不确定性',
    limitations: '限制',
    thingsToWatch: '后续观察',
    disciplineNotes: '投资纪律提醒',
    disclaimer: '免责声明',
    latestVersion: '最新版本',
    currentVersion: '当前版本',
    investmentTimeline: 'Investment Timeline',
    investmentTimelineSubtitle: 'analysis + manual journal',
    noTimeline: '暂无投资时间线记录',
    noTimelineDescription: '分析记录同步或手动投资日志创建后，会在这里显示。',
    addJournal: '记录投资想法',
    createJournal: '新增投资日志',
    journalPlaceholder: '记录你的投资观察、假设、担忧、复盘或情绪变化。原文会永久保留，AI 结构化需要手动触发。',
    saveJournal: '保存日志',
    manualEntry: '手动日志',
    analysisEntry: '分析记录',
    sourceUnavailable: '来源分析不可用',
    sourceAvailable: '来源分析可用',
    aiStructuring: 'AI整理',
    retryStructuring: '重试整理',
    structuringPending: '已进入队列，等待 AI 结构化。',
    structuringProcessing: '正在整理用户原文。',
    structuringFailed: 'AI 结构化失败。',
    structuredResult: '结构化结果',
    rawContent: '原文',
    journalType: '日志类型',
    thesis: '投资主张',
    reasons: '原因',
    assumptions: '假设',
    invalidationConditions: '失效条件',
    emotions: '情绪',
    cognitiveBias: '认知偏差',
    followUps: '后续事项',
    tags: '标签',
    market: '市场',
    recordId: '记录 ID',
    loading: '正在加载股票长期认知档案…',
    retry: '重试',
    pageError: '加载股票长期认知档案失败。',
    inputRequired: '请输入投资日志内容。',
    saved: '日志已保存',
    completed: '已完成',
    pending: '排队中',
    processing: '处理中',
    failed: '失败',
    rejected: '已拒绝',
    generating: '生成中',
    openStockArchive: '打开股票档案',
  },
  en: {
    archiveTitle: 'Stock Long-term Research Archive',
    archiveSubtitle: 'Combine current analysis, AI recap, and investment journals into one timeline.',
    currentAnalysis: 'Current Analysis',
    currentAnalysisSubtitle: 'latest analysis history',
    noCurrentAnalysis: 'No analysis history',
    noCurrentAnalysisDescription: 'Run at least one analysis first before viewing AI recap and the timeline.',
    openFullReport: 'Open full report',
    analysisSummary: 'Analysis summary',
    reportType: 'Report type',
    generatedAt: 'Generated at',
    model: 'Model',
    version: 'Version',
    promptVersion: 'Prompt version',
    aiOpinion: 'AI Opinion',
    aiOpinionSubtitle: 'research recap',
    generateOpinion: 'Generate AI recap',
    regenerateOpinion: 'Regenerate',
    noOpinion: 'No AI opinion yet',
    noOpinionDescription: 'AI opinions are generated only when triggered manually.',
    opinionPending: 'AI opinion has been queued.',
    opinionGenerating: 'AI opinion is being generated.',
    opinionFailed: 'AI opinion generation failed.',
    opinionRejected: 'AI opinion was rejected by safety rules.',
    sourceDeleted: 'Source analysis was deleted. The historical AI opinion is retained.',
    summary: 'Summary',
    keyFindings: 'Key findings',
    supportingEvidence: 'Supporting evidence',
    risks: 'Risks',
    uncertainties: 'Uncertainties',
    limitations: 'Limitations',
    thingsToWatch: 'Things to watch',
    disciplineNotes: 'Investment discipline notes',
    disclaimer: 'Disclaimer',
    latestVersion: 'Latest version',
    currentVersion: 'Current version',
    investmentTimeline: 'Investment Timeline',
    investmentTimelineSubtitle: 'analysis + manual journal',
    noTimeline: 'No timeline entries yet',
    noTimelineDescription: 'Analysis sync entries and manual journals will appear here.',
    addJournal: 'Record investment note',
    createJournal: 'New investment journal',
    journalPlaceholder: 'Write your observation, thesis, concerns, post-mortem, or emotion notes. Raw text is always preserved. AI structuring is manual.',
    saveJournal: 'Save journal',
    manualEntry: 'Manual note',
    analysisEntry: 'Analysis record',
    sourceUnavailable: 'Source analysis unavailable',
    sourceAvailable: 'Source analysis available',
    aiStructuring: 'AI structure',
    retryStructuring: 'Retry structuring',
    structuringPending: 'Queued for AI structuring.',
    structuringProcessing: 'Structuring raw user content.',
    structuringFailed: 'AI structuring failed.',
    structuredResult: 'Structured output',
    rawContent: 'Raw content',
    journalType: 'Journal type',
    thesis: 'Investment thesis',
    reasons: 'Reasons',
    assumptions: 'Assumptions',
    invalidationConditions: 'Invalidation conditions',
    emotions: 'Emotions',
    cognitiveBias: 'Cognitive bias',
    followUps: 'Follow-up items',
    tags: 'Tags',
    market: 'Market',
    recordId: 'Record ID',
    loading: 'Loading stock research archive…',
    retry: 'Retry',
    pageError: 'Failed to load the stock research archive.',
    inputRequired: 'Please enter journal content.',
    saved: 'Journal saved',
    completed: 'Completed',
    pending: 'Pending',
    processing: 'Processing',
    failed: 'Failed',
    rejected: 'Rejected',
    generating: 'Generating',
    openStockArchive: 'Open stock archive',
  },
} as const;

export function getStockDetailText(language: UiLanguage) {
  return STOCK_DETAIL_TEXT[language];
}

export function inferStockMarket(stockCode: string, explicitMarket?: string | null): string {
  const explicit = (explicitMarket ?? '').trim().toLowerCase();
  if (explicit) {
    return explicit;
  }

  const normalized = normalizeStockCode(stockCode).toUpperCase();
  if (normalized.startsWith('HK')) return 'hk';
  if (/^\d{6}$/.test(normalized)) return 'cn';
  if (normalized.endsWith('.T')) return 'jp';
  if (normalized.endsWith('.KS') || normalized.endsWith('.KQ')) return 'kr';
  if (normalized.endsWith('.TW') || normalized.endsWith('.TWO')) return 'tw';
  return 'us';
}

export function formatMarketLabel(market: string, language: UiLanguage): string {
  const normalized = market.trim().toLowerCase();
  const zhLabels: Record<string, string> = {
    cn: 'A股',
    hk: '港股',
    us: '美股',
    jp: '日股',
    kr: '韩股',
    tw: '台股',
  };
  const enLabels: Record<string, string> = {
    cn: 'CN',
    hk: 'HK',
    us: 'US',
    jp: 'JP',
    kr: 'KR',
    tw: 'TW',
  };
  const labels = language === 'zh' ? zhLabels : enLabels;
  return labels[normalized] ?? normalized.toUpperCase();
}

export function truncateText(value: string | null | undefined, maxLength = 180): string {
  const text = (value ?? '').trim();
  if (!text) return '';
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength)}…`;
}

export function extractStringArray(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .map((item) => (typeof item === 'string' ? item.trim() : ''))
      .filter(Boolean);
  }
  if (typeof value === 'string' && value.trim()) {
    return [value.trim()];
  }
  return [];
}

export function readStructuredField(record: Record<string, unknown> | null | undefined, ...keys: string[]): unknown {
  if (!record) return undefined;
  for (const key of keys) {
    if (key in record) {
      return record[key];
    }
  }
  return undefined;
}
