export type AIOpinionGenerationStatus = 'pending' | 'generating' | 'completed' | 'failed' | 'rejected';
export type AIOpinionSourceStatus = 'available' | 'deleted';

export interface AIOpinionItem {
  id: number;
  analysisHistoryId: number | null;
  analysisHistoryAvailable: boolean;
  version: number;
  isCurrent: boolean;
  generationStatus: AIOpinionGenerationStatus;
  sourceStatus: AIOpinionSourceStatus;
  title?: string | null;
  content?: string | null;
  conclusion?: string | null;
  outputJson?: Record<string, unknown> | null;
  evidence?: unknown[] | Record<string, unknown> | null;
  risks?: unknown[] | Record<string, unknown> | null;
  limitations?: unknown[] | Record<string, unknown> | null;
  watchItems?: unknown[] | Record<string, unknown> | null;
  model?: string | null;
  provider?: string | null;
  temperature?: number | null;
  promptVersion?: string | null;
  auditMetadata?: Record<string, unknown> | null;
  errorMessage?: string | null;
  contextHash?: string | null;
  retryCount: number;
  generatedAt?: string | null;
  feedbackValue?: string | null;
  feedbackNote?: string | null;
  feedbackUpdatedAt?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface AIOpinionListResponse {
  items: AIOpinionItem[];
  total: number;
}

export interface AIOpinionGenerateAccepted {
  opinion: AIOpinionItem;
  accepted: boolean;
  taskId: string;
  traceId: string;
  taskStatus: string;
  message?: string | null;
}
