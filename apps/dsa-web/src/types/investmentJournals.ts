import type { AIOpinionGenerationStatus } from './aiOpinions';

export type InvestmentJournalEntryType = 'analysis' | 'manual';
export type InvestmentJournalSourceStatus = 'available' | 'deleted';
export type InvestmentJournalAiProcessingStatus =
  | 'not_applicable'
  | 'pending'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'succeeded';

export interface JournalAnalysisHistoryRef {
  id: number;
  queryId?: string | null;
  reportType?: string | null;
  createdAt?: string | null;
}

export interface JournalCurrentAIOpinionRef {
  id: number;
  analysisHistoryId: number;
  version: number;
  generationStatus: AIOpinionGenerationStatus;
  conclusion?: string | null;
  createdAt?: string | null;
}

export interface InvestmentJournalEntryItem {
  id: number;
  stockCode: string;
  market: string;
  entryType: InvestmentJournalEntryType;
  sourceAnalysisHistoryId?: number | null;
  sourceStatus: InvestmentJournalSourceStatus;
  rawContent?: string | null;
  summarySnapshot?: string | null;
  riskSummary?: string | null;
  watchItems?: unknown[] | Record<string, unknown> | null;
  sourceLabel: string;
  structuredOutput?: Record<string, unknown> | null;
  aiProcessingStatus: InvestmentJournalAiProcessingStatus;
  model?: string | null;
  provider?: string | null;
  temperature?: number | null;
  promptVersion?: string | null;
  structuredVersion?: string | null;
  structuredAt?: string | null;
  structuredError?: string | null;
  analysisHistory?: JournalAnalysisHistoryRef | null;
  analysisHistoryAvailable: boolean;
  currentAiOpinion?: JournalCurrentAIOpinionRef | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface InvestmentJournalListResponse {
  items: InvestmentJournalEntryItem[];
  total: number;
  page: number;
  pageSize: number;
}

export interface ManualInvestmentJournalCreateRequest {
  stockCode: string;
  market: string;
  rawContent: string;
  summarySnapshot?: string;
}

export interface ManualInvestmentJournalUpdateRequest {
  rawContent?: string;
  summarySnapshot?: string;
}

export interface InvestmentJournalStructuringAccepted {
  entry: InvestmentJournalEntryItem;
  accepted: boolean;
  taskId: string;
  traceId: string;
  taskStatus: string;
  message?: string | null;
}
