import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import type { InvestmentJournalEntryItem } from '../../../types/investmentJournals';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';
import { InvestmentTimeline } from '../InvestmentTimeline';

const analysisItem: InvestmentJournalEntryItem = {
  id: 1,
  stockCode: '600519',
  market: 'cn',
  entryType: 'analysis',
  sourceStatus: 'available',
  summarySnapshot: '季度跟踪分析摘要',
  sourceLabel: 'analysis_history',
  aiProcessingStatus: 'not_applicable',
  analysisHistoryAvailable: true,
  currentAiOpinion: {
    id: 9,
    analysisHistoryId: 10,
    version: 1,
    generationStatus: 'completed',
    conclusion: '更适合作为长期跟踪对象而非短线交易。',
  },
  createdAt: '2026-07-10T10:00:00Z',
};

const manualItem: InvestmentJournalEntryItem = {
  id: 2,
  stockCode: '600519',
  market: 'cn',
  entryType: 'manual',
  sourceStatus: 'available',
  rawContent: '我需要重新验证竞争优势和估值框架。',
  sourceLabel: 'manual_note',
  aiProcessingStatus: 'completed',
  structuredOutput: {
    summary: '复核竞争优势与估值框架。',
    journal_type: 'research_note',
    reasons: ['估值不低'],
    risks: ['竞争加剧'],
    follow_up_items: ['跟踪中报'],
    tags: ['估值', '竞争'],
  },
  analysisHistoryAvailable: false,
  createdAt: '2026-07-10T12:00:00Z',
  structuredAt: '2026-07-10T12:10:00Z',
};

function renderTimeline(items: InvestmentJournalEntryItem[]) {
  window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
  const onCreateManual = vi.fn();
  const onStructure = vi.fn();
  const onRetryStructure = vi.fn();

  render(
    <UiLanguageProvider>
      <InvestmentTimeline
        items={items}
        language="zh"
        onCreateManual={onCreateManual}
        onStructure={onStructure}
        onRetryStructure={onRetryStructure}
      />
    </UiLanguageProvider>,
  );

  return { onCreateManual, onStructure, onRetryStructure };
}

describe('InvestmentTimeline', () => {
  it('renders analysis and manual items with structured output', () => {
    renderTimeline([manualItem, analysisItem]);

    expect(screen.getByText('季度跟踪分析摘要')).toBeInTheDocument();
    expect(screen.getByText('更适合作为长期跟踪对象而非短线交易。')).toBeInTheDocument();
    expect(screen.getByText('复核竞争优势与估值框架。')).toBeInTheDocument();
    expect(screen.getByText('research_note')).toBeInTheDocument();
    expect(screen.getByText('估值不低')).toBeInTheDocument();
    expect(screen.getByText('跟踪中报')).toBeInTheDocument();
  });

  it('shows failed manual entry and triggers retry', () => {
    const { onRetryStructure } = renderTimeline([
      {
        ...manualItem,
        id: 3,
        aiProcessingStatus: 'failed',
        structuredOutput: null,
        structuredError: 'invalid json',
      },
    ]);

    expect(screen.getByText('invalid json')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重试整理' }));
    expect(onRetryStructure).toHaveBeenCalledWith(3);
  });

  it('opens create manual note action from empty state', () => {
    const { onCreateManual } = renderTimeline([]);
    fireEvent.click(screen.getAllByRole('button', { name: '记录投资想法' })[0]);
    expect(onCreateManual).toHaveBeenCalledTimes(1);
  });
});
