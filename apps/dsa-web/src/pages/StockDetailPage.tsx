import type React from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { aiOpinionsApi } from '../api/aiOpinions';
import { getParsedApiError } from '../api/error';
import { historyApi } from '../api/history';
import { investmentJournalsApi } from '../api/investmentJournals';
import { AppPage, ApiErrorAlert, Loading } from '../components/common';
import {
  AIOpinionCard,
  AddJournalDialog,
  CurrentAnalysisCard,
  InvestmentTimeline,
  StockDetailHeader,
  getStockDetailText,
  inferStockMarket,
} from '../components/stock-detail';
import { ReportMarkdownDrawer } from '../components/report/ReportMarkdownDrawer';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import type { AIOpinionItem } from '../types/aiOpinions';
import type { HistoryItem, AnalysisReport } from '../types/analysis';
import type { InvestmentJournalEntryItem } from '../types/investmentJournals';
import { normalizeStockCode } from '../utils/stockCode';

function isOpinionPollingNeeded(opinion: AIOpinionItem | null): boolean {
  return opinion?.generationStatus === 'pending' || opinion?.generationStatus === 'generating';
}

function isJournalPollingNeeded(items: InvestmentJournalEntryItem[]): boolean {
  return items.some(
    (item) => item.entryType === 'manual' && (item.aiProcessingStatus === 'pending' || item.aiProcessingStatus === 'processing'),
  );
}

const StockDetailPage: React.FC = () => {
  const { stockCode: stockCodeParam } = useParams<{ stockCode: string }>();
  const [searchParams] = useSearchParams();
  const { language } = useUiLanguage();
  const text = getStockDetailText(language);

  const normalizedStockCode = useMemo(
    () => normalizeStockCode(stockCodeParam ?? '').toUpperCase(),
    [stockCodeParam],
  );
  const market = useMemo(
    () => inferStockMarket(normalizedStockCode, searchParams.get('market')),
    [normalizedStockCode, searchParams],
  );
  const requestedRecordId = useMemo(() => {
    const raw = searchParams.get('recordId');
    if (!raw) return null;
    const parsed = Number(raw);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [searchParams]);

  const [isLoading, setIsLoading] = useState(true);
  const [pageError, setPageError] = useState<unknown>(null);
  const [historyItem, setHistoryItem] = useState<HistoryItem | null>(null);
  const [report, setReport] = useState<AnalysisReport | null>(null);
  const [opinion, setOpinion] = useState<AIOpinionItem | null>(null);
  const [journalEntries, setJournalEntries] = useState<InvestmentJournalEntryItem[]>([]);
  const [isReportDrawerOpen, setIsReportDrawerOpen] = useState(false);
  const [isJournalDialogOpen, setIsJournalDialogOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isOpinionActionLoading, setIsOpinionActionLoading] = useState(false);
  const [isJournalSubmitting, setIsJournalSubmitting] = useState(false);
  const [structuringIds, setStructuringIds] = useState<number[]>([]);

  const selectedAnalysisHistoryId = historyItem?.id ?? report?.meta.id ?? null;
  const stockName = report?.meta.stockName || historyItem?.stockName || null;

  const refreshSecondaryData = useCallback(async (analysisHistoryId: number | null) => {
    const [journalResponse, opinionResponse] = await Promise.all([
      investmentJournalsApi.listByStock({
        stockCode: normalizedStockCode,
        market,
        page: 1,
        pageSize: 100,
      }),
      analysisHistoryId
        ? aiOpinionsApi.list({ analysisHistoryId, currentOnly: false })
        : Promise.resolve({ items: [], total: 0 }),
    ]);
    setJournalEntries(journalResponse.items);
    setOpinion(opinionResponse.items[0] ?? null);
  }, [market, normalizedStockCode]);

  const loadPage = useCallback(async () => {
    if (!normalizedStockCode) {
      setPageError(new Error('stockCode is required'));
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setPageError(null);

    try {
      const [historyResponse, journalResponse] = await Promise.all([
        historyApi.getList({
          stockCode: normalizedStockCode,
          page: 1,
          limit: 20,
        }),
        investmentJournalsApi.listByStock({
          stockCode: normalizedStockCode,
          market,
          page: 1,
          pageSize: 100,
        }),
      ]);

      const filteredHistoryItems = historyResponse.items.filter((item) => item.reportType !== 'market_review');
      const selectedHistory = requestedRecordId
        ? filteredHistoryItems.find((item) => item.id === requestedRecordId) ?? filteredHistoryItems[0] ?? null
        : filteredHistoryItems[0] ?? null;

      setHistoryItem(selectedHistory);
      setJournalEntries(journalResponse.items);

      if (!selectedHistory) {
        setReport(null);
        setOpinion(null);
        return;
      }

      const [historyDetail, opinionList] = await Promise.all([
        historyApi.getDetail(selectedHistory.id),
        aiOpinionsApi.list({ analysisHistoryId: selectedHistory.id, currentOnly: false }),
      ]);

      setReport(historyDetail);
      setOpinion(opinionList.items[0] ?? null);
    } catch (error) {
      setPageError(error);
    } finally {
      setIsLoading(false);
    }
  }, [market, normalizedStockCode, requestedRecordId]);

  useEffect(() => {
    void loadPage();
  }, [loadPage]);

  useEffect(() => {
    if (!selectedAnalysisHistoryId && !journalEntries.length) return undefined;
    if (!isOpinionPollingNeeded(opinion) && !isJournalPollingNeeded(journalEntries)) return undefined;

    const timer = window.setInterval(() => {
      void refreshSecondaryData(selectedAnalysisHistoryId);
    }, 2500);

    return () => {
      window.clearInterval(timer);
    };
  }, [journalEntries, opinion, refreshSecondaryData, selectedAnalysisHistoryId]);

  useEffect(() => {
    setStructuringIds((current) => current.filter((id) => {
      const item = journalEntries.find((entry) => entry.id === id);
      return item ? item.aiProcessingStatus === 'pending' || item.aiProcessingStatus === 'processing' : false;
    }));
  }, [journalEntries]);

  const handleGenerateOpinion = useCallback(async () => {
    if (!selectedAnalysisHistoryId) return;
    setActionError(null);
    setIsOpinionActionLoading(true);
    try {
      const accepted = await aiOpinionsApi.generate(selectedAnalysisHistoryId);
      setOpinion(accepted.opinion);
      await refreshSecondaryData(selectedAnalysisHistoryId);
    } catch (error) {
      setActionError(getParsedApiError(error).message);
    } finally {
      setIsOpinionActionLoading(false);
    }
  }, [refreshSecondaryData, selectedAnalysisHistoryId]);

  const handleRegenerateOpinion = useCallback(async (opinionId: number) => {
    setActionError(null);
    setIsOpinionActionLoading(true);
    try {
      const accepted = await aiOpinionsApi.regenerate(opinionId);
      setOpinion(accepted.opinion);
      await refreshSecondaryData(accepted.opinion.analysisHistoryId);
    } catch (error) {
      setActionError(getParsedApiError(error).message);
    } finally {
      setIsOpinionActionLoading(false);
    }
  }, [refreshSecondaryData]);

  const handleCreateManualJournal = useCallback(async (rawContent: string) => {
    setActionError(null);
    setIsJournalSubmitting(true);
    try {
      await investmentJournalsApi.createManual({
        stockCode: normalizedStockCode,
        market,
        rawContent,
      });
      setIsJournalDialogOpen(false);
      await refreshSecondaryData(selectedAnalysisHistoryId);
    } catch (error) {
      setActionError(getParsedApiError(error).message);
      throw error;
    } finally {
      setIsJournalSubmitting(false);
    }
  }, [market, normalizedStockCode, refreshSecondaryData, selectedAnalysisHistoryId]);

  const handleStructure = useCallback(async (entryId: number) => {
    setActionError(null);
    setStructuringIds((current) => Array.from(new Set([...current, entryId])));
    try {
      const accepted = await investmentJournalsApi.structure(entryId);
      setJournalEntries((current) => current.map((item) => (item.id === entryId ? accepted.entry : item)));
      await refreshSecondaryData(selectedAnalysisHistoryId);
    } catch (error) {
      setStructuringIds((current) => current.filter((id) => id !== entryId));
      setActionError(getParsedApiError(error).message);
    }
  }, [refreshSecondaryData, selectedAnalysisHistoryId]);

  const handleRetryStructure = useCallback(async (entryId: number) => {
    setActionError(null);
    setStructuringIds((current) => Array.from(new Set([...current, entryId])));
    try {
      const accepted = await investmentJournalsApi.retryStructure(entryId);
      setJournalEntries((current) => current.map((item) => (item.id === entryId ? accepted.entry : item)));
      await refreshSecondaryData(selectedAnalysisHistoryId);
    } catch (error) {
      setStructuringIds((current) => current.filter((id) => id !== entryId));
      setActionError(getParsedApiError(error).message);
    }
  }, [refreshSecondaryData, selectedAnalysisHistoryId]);

  if (isLoading) {
    return (
      <AppPage>
        <Loading label={text.loading} />
      </AppPage>
    );
  }

  if (pageError) {
    return (
      <AppPage className="space-y-6">
        <ApiErrorAlert
          error={getParsedApiError(pageError)}
          actionLabel={text.retry}
          onAction={() => void loadPage()}
        />
      </AppPage>
    );
  }

  return (
    <AppPage className="space-y-6" data-testid="stock-detail-page">
      <StockDetailHeader
        stockCode={normalizedStockCode}
        market={market}
        stockName={stockName}
        language={language}
      />

      {actionError ? (
        <ApiErrorAlert
          error={{
            title: text.pageError,
            message: actionError,
            rawMessage: actionError,
            category: 'http_error',
          }}
          onDismiss={() => setActionError(null)}
        />
      ) : null}

      <CurrentAnalysisCard
        report={report}
        language={language}
        onOpenReport={() => setIsReportDrawerOpen(true)}
      />

      <AIOpinionCard
        opinion={opinion}
        analysisHistoryId={selectedAnalysisHistoryId}
        language={language}
        actionLoading={isOpinionActionLoading}
        onGenerate={() => void handleGenerateOpinion()}
        onRegenerate={(opinionId) => void handleRegenerateOpinion(opinionId)}
      />

      <InvestmentTimeline
        items={journalEntries}
        language={language}
        onCreateManual={() => setIsJournalDialogOpen(true)}
        onStructure={(entryId) => void handleStructure(entryId)}
        onRetryStructure={(entryId) => void handleRetryStructure(entryId)}
        structuringIds={structuringIds}
      />

      {isJournalDialogOpen ? (
        <AddJournalDialog
          isOpen={isJournalDialogOpen}
          stockCode={normalizedStockCode}
          market={market}
          language={language}
          isSubmitting={isJournalSubmitting}
          error={actionError}
          onClose={() => setIsJournalDialogOpen(false)}
          onSubmit={handleCreateManualJournal}
        />
      ) : null}

      {isReportDrawerOpen && report?.meta.id ? (
        <ReportMarkdownDrawer
          recordId={report.meta.id}
          stockName={report.meta.stockName}
          stockCode={report.meta.stockCode}
          reportLanguage={report.meta.reportLanguage}
          onClose={() => setIsReportDrawerOpen(false)}
        />
      ) : null}
    </AppPage>
  );
};

export default StockDetailPage;
