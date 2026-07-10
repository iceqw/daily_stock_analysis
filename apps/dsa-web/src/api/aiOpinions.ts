import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  AIOpinionGenerateAccepted,
  AIOpinionItem,
  AIOpinionListResponse,
} from '../types/aiOpinions';

export interface ListAIOpinionsParams {
  analysisHistoryId: number;
  currentOnly?: boolean;
}

export const aiOpinionsApi = {
  list: async (params: ListAIOpinionsParams): Promise<AIOpinionListResponse> => {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/ai-opinions', {
      params: {
        analysis_history_id: params.analysisHistoryId,
        current_only: params.currentOnly ?? false,
      },
    });
    return toCamelCase<AIOpinionListResponse>(response.data);
  },

  get: async (id: number): Promise<AIOpinionItem> => {
    const response = await apiClient.get<Record<string, unknown>>(`/api/v1/ai-opinions/${id}`);
    return toCamelCase<AIOpinionItem>(response.data);
  },

  generate: async (analysisHistoryId: number): Promise<AIOpinionGenerateAccepted> => {
    const response = await apiClient.post<Record<string, unknown>>(
      `/api/v1/ai-opinions/generate/${analysisHistoryId}`,
    );
    return toCamelCase<AIOpinionGenerateAccepted>(response.data);
  },

  regenerate: async (id: number): Promise<AIOpinionGenerateAccepted> => {
    const response = await apiClient.post<Record<string, unknown>>(`/api/v1/ai-opinions/${id}/regenerate`);
    return toCamelCase<AIOpinionGenerateAccepted>(response.data);
  },
};
