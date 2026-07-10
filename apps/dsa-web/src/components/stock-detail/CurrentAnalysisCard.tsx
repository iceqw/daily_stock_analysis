import type React from 'react';
import type { AnalysisReport } from '../../types/analysis';
import { Button, EmptyState, SectionCard } from '../common';
import { formatDateTime, formatReportType } from '../../utils/format';
import type { UiLanguage } from '../../i18n/uiText';
import { getStockDetailText } from './utils';

interface CurrentAnalysisCardProps {
  report: AnalysisReport | null;
  language: UiLanguage;
  onOpenReport: () => void;
}

export const CurrentAnalysisCard: React.FC<CurrentAnalysisCardProps> = ({
  report,
  language,
  onOpenReport,
}) => {
  const text = getStockDetailText(language);

  return (
    <SectionCard
      title={text.currentAnalysis}
      subtitle={text.currentAnalysisSubtitle}
      actions={report ? (
        <Button variant="outline" size="sm" onClick={onOpenReport}>
          {text.openFullReport}
        </Button>
      ) : null}
    >
      {!report ? (
        <EmptyState
          title={text.noCurrentAnalysis}
          description={text.noCurrentAnalysisDescription}
        />
      ) : (
        <div className="space-y-5">
          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-2xl border border-border/60 bg-surface-2/80 p-4">
              <div className="text-xs uppercase tracking-[0.24em] text-muted-text">{text.generatedAt}</div>
              <div className="mt-2 text-sm text-foreground">{formatDateTime(report.meta.createdAt)}</div>
            </div>
            <div className="rounded-2xl border border-border/60 bg-surface-2/80 p-4">
              <div className="text-xs uppercase tracking-[0.24em] text-muted-text">{text.reportType}</div>
              <div className="mt-2 text-sm text-foreground">{formatReportType(report.meta.reportType)}</div>
            </div>
            <div className="rounded-2xl border border-border/60 bg-surface-2/80 p-4">
              <div className="text-xs uppercase tracking-[0.24em] text-muted-text">{text.model}</div>
              <div className="mt-2 text-sm text-foreground">{report.meta.modelUsed || '—'}</div>
            </div>
          </div>
          <div className="rounded-2xl border border-border/60 bg-surface-2/60 p-4">
            <div className="text-xs uppercase tracking-[0.24em] text-muted-text">{text.analysisSummary}</div>
            <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-foreground">
              {report.summary.analysisSummary || '—'}
            </p>
          </div>
        </div>
      )}
    </SectionCard>
  );
};
