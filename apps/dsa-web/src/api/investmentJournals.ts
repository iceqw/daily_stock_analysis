import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  InvestmentJournalEntryItem,
  InvestmentJournalListResponse,
  InvestmentJournalStructuringAccepted,
  ManualInvestmentJournalCreateRequest,
  ManualInvestmentJournalUpdateRequest,
} from '../types/investmentJournals';

export interface ListInvestmentJournalParams {
  stockCode: string;
  market: string;
  entryType?: 'analysis' | 'manual';
  page?: number;
  pageSize?: number;
}

export const investmentJournalsApi = {
  listByStock: async (params: ListInvestmentJournalParams): Promise<InvestmentJournalListResponse> => {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/investment-journals', {
      params: {
        stock_code: params.stockCode,
        market: params.market,
        entry_type: params.entryType,
        page: params.page ?? 1,
        page_size: params.pageSize ?? 50,
      },
    });
    return toCamelCase<InvestmentJournalListResponse>(response.data);
  },

  get: async (id: number): Promise<InvestmentJournalEntryItem> => {
    const response = await apiClient.get<Record<string, unknown>>(`/api/v1/investment-journals/${id}`);
    return toCamelCase<InvestmentJournalEntryItem>(response.data);
  },

  createManual: async (payload: ManualInvestmentJournalCreateRequest): Promise<InvestmentJournalEntryItem> => {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/investment-journals/manual', {
      stock_code: payload.stockCode,
      market: payload.market,
      raw_content: payload.rawContent,
      summary_snapshot: payload.summarySnapshot,
    });
    return toCamelCase<InvestmentJournalEntryItem>(response.data);
  },

  updateManual: async (
    id: number,
    payload: ManualInvestmentJournalUpdateRequest,
  ): Promise<InvestmentJournalEntryItem> => {
    const response = await apiClient.patch<Record<string, unknown>>(`/api/v1/investment-journals/manual/${id}`, {
      raw_content: payload.rawContent,
      summary_snapshot: payload.summarySnapshot,
    });
    return toCamelCase<InvestmentJournalEntryItem>(response.data);
  },

  structure: async (id: number): Promise<InvestmentJournalStructuringAccepted> => {
    const response = await apiClient.post<Record<string, unknown>>(`/api/v1/investment-journals/${id}/structure`);
    return toCamelCase<InvestmentJournalStructuringAccepted>(response.data);
  },

  retryStructure: async (id: number): Promise<InvestmentJournalStructuringAccepted> => {
    const response = await apiClient.post<Record<string, unknown>>(`/api/v1/investment-journals/${id}/retry-structure`);
    return toCamelCase<InvestmentJournalStructuringAccepted>(response.data);
  },
};
