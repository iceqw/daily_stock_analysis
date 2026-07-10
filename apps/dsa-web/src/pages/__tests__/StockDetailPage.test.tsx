import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { aiOpinionsApi } from '../../api/aiOpinions';
import { historyApi } from '../../api/history';
import { investmentJournalsApi } from '../../api/investmentJournals';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';
import StockDetailPage from '../StockDetailPage';

vi.mock('../../api/history', () => ({
  historyApi: {
    getList: vi.fn(),
    getDetail: vi.fn(),
  },
}));

vi.mock('../../api/aiOpinions', () => ({
  aiOpinionsApi: {
    list: vi.fn(),
    generate: vi.fn(),
    regenerate: vi.fn(),
    get: vi.fn(),
  },
}));

vi.mock('../../api/investmentJournals', () => ({
  investmentJournalsApi: {
    listByStock: vi.fn(),
    createManual: vi.fn(),
    updateManual: vi.fn(),
    structure: vi.fn(),
    retryStructure: vi.fn(),
    get: vi.fn(),
  },
}));

vi.mock('../../components/report/ReportMarkdownDrawer', () => ({
  ReportMarkdownDrawer: ({ stockCode }: { stockCode: string }) => <div>mock report drawer {stockCode}</div>,
}));

const historyItem = {
  id: 11,
  queryId: 'q-11',
  stockCode: '600519',
  stockName: '贵州茅台',
  reportType: 'detailed' as const,
  analysisSummary: '最新一轮分析摘要',
  createdAt: '2026-07-10T09:00:00Z',
};

const historyDetail = {
  meta: {
    id: 11,
    queryId: 'q-11',
    stockCode: '600519',
    stockName: '贵州茅台',
    reportType: 'detailed' as const,
    reportLanguage: 'zh' as const,
    createdAt: '2026-07-10T09:00:00Z',
    modelUsed: 'gpt-test',
  },
  summary: {
    analysisSummary: '最新一轮分析摘要',
    operationAdvice: '继续跟踪',
    trendPrediction: '震荡偏强',
    sentimentScore: 66,
  },
};

function renderPage(initialPath = '/stocks/600519?market=cn') {
  window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
  return render(
    <UiLanguageProvider>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/stocks/:stockCode" element={<StockDetailPage />} />
        </Routes>
      </MemoryRouter>
    </UiLanguageProvider>,
  );
}

describe('StockDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it('renders empty state when no analysis exists', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 0,
      page: 1,
      limit: 20,
      items: [],
    });
    vi.mocked(investmentJournalsApi.listByStock).mockResolvedValue({
      total: 0,
      page: 1,
      pageSize: 100,
      items: [],
    });

    renderPage();

    expect(await screen.findByText('暂无分析记录')).toBeInTheDocument();
    expect(screen.getByText('暂无 AI 复盘')).toBeInTheDocument();
    expect(screen.getByText('暂无投资时间线记录')).toBeInTheDocument();
  });

  it('renders page error state', async () => {
    vi.mocked(historyApi.getList).mockRejectedValue(new Error('network down'));
    vi.mocked(investmentJournalsApi.listByStock).mockResolvedValue({
      total: 0,
      page: 1,
      pageSize: 100,
      items: [],
    });

    renderPage();

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/network down/i)).toBeInTheDocument();
  });

  it('creates manual journal entry from dialog', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 1,
      page: 1,
      limit: 20,
      items: [historyItem],
    });
    vi.mocked(historyApi.getDetail).mockResolvedValue(historyDetail);
    vi.mocked(aiOpinionsApi.list).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(investmentJournalsApi.listByStock)
      .mockResolvedValueOnce({ total: 0, page: 1, pageSize: 100, items: [] })
      .mockResolvedValueOnce({ total: 1, page: 1, pageSize: 100, items: [{
        id: 7,
        stockCode: '600519',
        market: 'cn',
        entryType: 'manual',
        sourceStatus: 'available',
        rawContent: '补充了新的投资假设',
        sourceLabel: 'manual_note',
        aiProcessingStatus: 'pending',
        analysisHistoryAvailable: false,
        createdAt: '2026-07-10T12:00:00Z',
      }] });
    vi.mocked(investmentJournalsApi.createManual).mockResolvedValue({
      id: 7,
      stockCode: '600519',
      market: 'cn',
      entryType: 'manual',
      sourceStatus: 'available',
      rawContent: '补充了新的投资假设',
      sourceLabel: 'manual_note',
      aiProcessingStatus: 'pending',
      analysisHistoryAvailable: false,
      createdAt: '2026-07-10T12:00:00Z',
    });

    renderPage();

    await screen.findByText('最新一轮分析摘要');
    fireEvent.click(screen.getAllByRole('button', { name: '记录投资想法' })[0]);
    fireEvent.change(screen.getByLabelText('原文'), { target: { value: '补充了新的投资假设' } });
    fireEvent.click(screen.getByRole('button', { name: '保存日志' }));

    await waitFor(() => {
      expect(investmentJournalsApi.createManual).toHaveBeenCalledWith({
        stockCode: '600519',
        market: 'cn',
        rawContent: '补充了新的投资假设',
      });
    });
    expect(await screen.findByText('补充了新的投资假设')).toBeInTheDocument();
  });

  it('triggers AI opinion generation and refreshes to completed status', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 1,
      page: 1,
      limit: 20,
      items: [historyItem],
    });
    vi.mocked(historyApi.getDetail).mockResolvedValue(historyDetail);
    vi.mocked(investmentJournalsApi.listByStock)
      .mockResolvedValueOnce({ total: 0, page: 1, pageSize: 100, items: [] })
      .mockResolvedValueOnce({ total: 0, page: 1, pageSize: 100, items: [] })
      .mockResolvedValue({ total: 0, page: 1, pageSize: 100, items: [] });
    vi.mocked(aiOpinionsApi.list)
      .mockResolvedValueOnce({ items: [], total: 0 })
      .mockResolvedValueOnce({
        items: [{
          id: 99,
          analysisHistoryId: 11,
          analysisHistoryAvailable: true,
          version: 1,
          isCurrent: false,
          generationStatus: 'pending',
          sourceStatus: 'available',
          retryCount: 0,
        }],
        total: 1,
      })
      .mockResolvedValue({
        items: [{
          id: 99,
          analysisHistoryId: 11,
          analysisHistoryAvailable: true,
          version: 1,
          isCurrent: true,
          generationStatus: 'completed',
          sourceStatus: 'available',
          outputJson: {
            summary: '完成 AI 复盘。',
            key_findings: ['估值需要耐心'],
            risks: ['宏观波动'],
            limitations: ['不提供交易建议'],
            things_to_watch: ['中报'],
            disclaimer: '仅用于研究整理，不构成投资建议。',
          },
          retryCount: 0,
          generatedAt: '2026-07-10T12:30:00Z',
        }],
        total: 1,
      });
    vi.mocked(aiOpinionsApi.generate).mockResolvedValue({
      accepted: true,
      taskId: 'task-1',
      traceId: 'task-1',
      taskStatus: 'pending',
      opinion: {
        id: 99,
        analysisHistoryId: 11,
        analysisHistoryAvailable: true,
        version: 1,
        isCurrent: false,
        generationStatus: 'pending',
        sourceStatus: 'available',
        retryCount: 0,
      },
    });
    const setIntervalSpy = vi.spyOn(window, 'setInterval').mockImplementation((callback: TimerHandler) => {
      if (typeof callback === 'function') {
        void callback();
      }
      return 1;
    });
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval').mockImplementation(() => undefined);

    renderPage();

    await screen.findByText('暂无 AI 复盘');
    fireEvent.click(screen.getAllByRole('button', { name: '生成 AI 复盘' })[0]);

    await waitFor(() => {
      expect(aiOpinionsApi.generate).toHaveBeenCalledWith(11);
    });

    await waitFor(() => {
      expect(screen.getByText('完成 AI 复盘。')).toBeInTheDocument();
      expect(screen.getByText('估值需要耐心')).toBeInTheDocument();
    });
    expect(aiOpinionsApi.list).toHaveBeenCalledTimes(3);
    expect(setIntervalSpy).toHaveBeenCalled();
    expect(clearIntervalSpy).toHaveBeenCalled();
  });
});
