import apiClient from './index';
import { toCamelCase } from './utils';

export type AIOpinionGenerationStatus = 'pending' | 'generating' | 'completed' | 'failed' | 'rejected';

export interface AIOpinionEvidence {
  statement?: string;
  sourceRef?: string | null;
  [key: string]: unknown;
}

export interface AIOpinionPrincipleRef {
  principleId: number;
  principleVersion: number;
  category: string;
  severity: string;
  title: string;
  assessmentStatus: 'aligned' | 'at_risk' | 'violated' | 'not_applicable' | 'insufficient_evidence' | null;
  evidence?: AIOpinionEvidence[] | null;
  explanation?: string | null;
  confidence?: number | null;
}

export interface AIOpinionListItem {
  id: number;
  analysisHistoryId: number | null;
  analysisHistoryAvailable: boolean;
  version: number;
  isCurrent: boolean;
  generationStatus: AIOpinionGenerationStatus;
  sourceStatus: 'available' | 'deleted';
  title?: string | null;
  content?: string | null;
  conclusion?: string | null;
  outputJson?: Record<string, unknown> | null;
  evidence?: AIOpinionEvidence[] | null;
  risks?: string[] | null;
  limitations?: string[] | null;
  watchItems?: string[] | null;
  model?: string | null;
  provider?: string | null;
  promptVersion?: string | null;
  errorMessage?: string | null;
  principleRefs: AIOpinionPrincipleRef[];
  retryCount: number;
  generatedAt?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  analysisStockCode?: string | null;
  analysisStockName?: string | null;
}

export type AIOpinionDetail = AIOpinionListItem;

export interface AIOpinionGenerateAccepted {
  opinion: AIOpinionDetail;
  accepted: boolean;
  taskId: string;
  traceId: string;
  taskStatus: string;
  message?: string | null;
}

export interface AIOpinionGenerationStatusResponse {
  items: AIOpinionListItem[];
  total: number;
  page: number;
  pageSize: number;
}

const normalizeItem = (value: unknown): AIOpinionDetail => {
  const item = toCamelCase<AIOpinionDetail>(value);
  return { ...item, principleRefs: item.principleRefs || [] };
};

export const aiOpinionsApi = {
  listByAnalysisHistory: async (analysisHistoryId: number): Promise<AIOpinionGenerationStatusResponse> => {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/ai-opinions', {
      params: { analysis_history_id: analysisHistoryId, page: 1, page_size: 100 },
    });
    const data = toCamelCase<{ items?: unknown[]; total: number; page: number; pageSize: number }>(response.data);
    return {
      items: (data.items || []).map(normalizeItem),
      total: data.total,
      page: data.page,
      pageSize: data.pageSize,
    };
  },

  get: async (opinionId: number): Promise<AIOpinionDetail> => {
    const response = await apiClient.get(`/api/v1/ai-opinions/${opinionId}`);
    return normalizeItem(response.data);
  },

  generate: async (analysisHistoryId: number): Promise<AIOpinionGenerateAccepted> => {
    const response = await apiClient.post(`/api/v1/ai-opinions/generate/${analysisHistoryId}`);
    return toCamelCase<AIOpinionGenerateAccepted>(response.data);
  },

  retry: async (opinionId: number): Promise<AIOpinionGenerateAccepted> => {
    const response = await apiClient.post(`/api/v1/ai-opinions/${opinionId}/retry`);
    return toCamelCase<AIOpinionGenerateAccepted>(response.data);
  },

  regenerate: async (opinionId: number): Promise<AIOpinionGenerateAccepted> => {
    const response = await apiClient.post(`/api/v1/ai-opinions/${opinionId}/regenerate`);
    return toCamelCase<AIOpinionGenerateAccepted>(response.data);
  },
};
