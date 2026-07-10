import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import type { AIOpinionItem } from '../../../types/aiOpinions';
import { AIOpinionCard } from '../AIOpinionCard';

function renderCard(props: Partial<React.ComponentProps<typeof AIOpinionCard>> = {}) {
  const opinion: AIOpinionItem = {
    id: 1,
    analysisHistoryId: 9,
    analysisHistoryAvailable: true,
    version: 2,
    isCurrent: true,
    generationStatus: 'completed',
    sourceStatus: 'available',
    outputJson: {
      summary: '形成了更清晰的长期跟踪框架。',
      key_findings: ['盈利质量改善', '估值不便宜'],
      risks: ['行业波动'],
      limitations: ['不包含未来事件预测'],
      things_to_watch: ['中报披露'],
      disclaimer: '仅用于研究整理，不构成投资建议。',
    },
    retryCount: 0,
    model: 'gpt-test',
    promptVersion: 'v1',
    generatedAt: '2026-07-10T12:00:00Z',
  };

  const onGenerate = vi.fn();
  const onRegenerate = vi.fn();

  render(
    <UiLanguageProvider>
      <AIOpinionCard
        opinion={opinion}
        analysisHistoryId={9}
        language="zh"
        onGenerate={onGenerate}
        onRegenerate={onRegenerate}
        {...props}
      />
    </UiLanguageProvider>,
  );

  return {
    onGenerate,
    onRegenerate,
  };
}

describe('AIOpinionCard', () => {
  it('renders completed AI opinion fields', () => {
    renderCard();

    expect(screen.getByText('AI Opinion')).toBeInTheDocument();
    expect(screen.getByText('形成了更清晰的长期跟踪框架。')).toBeInTheDocument();
    expect(screen.getByText('盈利质量改善')).toBeInTheDocument();
    expect(screen.getByText('行业波动')).toBeInTheDocument();
    expect(screen.getByText('仅用于研究整理，不构成投资建议。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重新生成' })).toBeInTheDocument();
  });

  it('renders pending status without allowing duplicate regenerate', () => {
    renderCard({
      opinion: {
        id: 2,
        analysisHistoryId: 9,
        analysisHistoryAvailable: true,
        version: 3,
        isCurrent: false,
        generationStatus: 'pending',
        sourceStatus: 'available',
        retryCount: 0,
      },
    });

    expect(screen.getByText('AI Opinion 已进入队列，正在等待执行。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重新生成' })).toBeDisabled();
  });

  it('shows generate button when no opinion exists', () => {
    const { onGenerate } = renderCard({
      opinion: null,
      analysisHistoryId: 9,
    });

    fireEvent.click(screen.getAllByRole('button', { name: '生成 AI 复盘' })[0]);
    expect(onGenerate).toHaveBeenCalledTimes(1);
  });

  it('renders failed state and supports regenerate', () => {
    const { onRegenerate } = renderCard({
      opinion: {
        id: 8,
        analysisHistoryId: 9,
        analysisHistoryAvailable: true,
        version: 4,
        isCurrent: false,
        generationStatus: 'failed',
        sourceStatus: 'available',
        errorMessage: 'LLM timeout',
        retryCount: 1,
      },
    });

    expect(screen.getByText('LLM timeout')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重新生成' }));
    expect(onRegenerate).toHaveBeenCalledWith(8);
  });
});
