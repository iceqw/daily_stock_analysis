import type React from 'react';
import type { AIOpinionItem } from '../../types/aiOpinions';
import { Badge, Button, EmptyState, InlineAlert, SectionCard } from '../common';
import { formatDateTime } from '../../utils/format';
import type { UiLanguage } from '../../i18n/uiText';
import {
  extractStringArray,
  getStockDetailText,
  readStructuredField,
} from './utils';

interface AIOpinionCardProps {
  opinion: AIOpinionItem | null;
  analysisHistoryId?: number | null;
  language: UiLanguage;
  actionLoading?: boolean;
  onGenerate: () => void;
  onRegenerate: (opinionId: number) => void;
}

function renderStringList(items: string[]) {
  if (items.length === 0) return <p className="text-sm text-secondary-text">—</p>;
  return (
    <ul className="space-y-2 text-sm text-foreground">
      {items.map((item) => (
        <li key={item} className="flex gap-2">
          <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-cyan" />
          <span className="leading-6">{item}</span>
        </li>
      ))}
    </ul>
  );
}

export const AIOpinionCard: React.FC<AIOpinionCardProps> = ({
  opinion,
  analysisHistoryId,
  language,
  actionLoading = false,
  onGenerate,
  onRegenerate,
}) => {
  const text = getStockDetailText(language);
  const status = opinion?.generationStatus;
  const output = (opinion?.outputJson as Record<string, unknown> | null | undefined) ?? null;

  const summary = typeof readStructuredField(output, 'summary') === 'string'
    ? String(readStructuredField(output, 'summary'))
    : opinion?.conclusion || opinion?.content || '';
  const keyFindings = extractStringArray(readStructuredField(output, 'keyFindings', 'key_findings'));
  const supportingEvidence = extractStringArray(readStructuredField(output, 'supportingEvidence', 'supporting_evidence'));
  const risks = extractStringArray(readStructuredField(output, 'risks'));
  const uncertainties = extractStringArray(readStructuredField(output, 'uncertainties'));
  const limitations = extractStringArray(readStructuredField(output, 'limitations'));
  const watchItems = extractStringArray(readStructuredField(output, 'thingsToWatch', 'things_to_watch'));
  const disciplineNotes = extractStringArray(
    readStructuredField(output, 'investmentDisciplineNotes', 'investment_discipline_notes'),
  );
  const disclaimer = typeof readStructuredField(output, 'disclaimer') === 'string'
    ? String(readStructuredField(output, 'disclaimer'))
    : '';

  const statusBadgeVariant = status === 'completed'
    ? 'success'
    : status === 'failed' || status === 'rejected'
      ? 'danger'
      : 'warning';
  const statusLabel = status ? text[status] : '';

  const renderStatusAlert = () => {
    if (status === 'pending') {
      return <InlineAlert variant="info" message={text.opinionPending} />;
    }
    if (status === 'generating') {
      return <InlineAlert variant="info" message={text.opinionGenerating} />;
    }
    if (status === 'failed') {
      return <InlineAlert variant="danger" message={opinion?.errorMessage || text.opinionFailed} />;
    }
    if (status === 'rejected') {
      return <InlineAlert variant="warning" message={opinion?.errorMessage || text.opinionRejected} />;
    }
    return null;
  };

  return (
    <SectionCard
      title={text.aiOpinion}
      subtitle={text.aiOpinionSubtitle}
      actions={opinion ? (
        <Button
          variant="outline"
          size="sm"
          isLoading={actionLoading}
          onClick={() => onRegenerate(opinion.id)}
          disabled={status === 'pending' || status === 'generating'}
        >
          {text.regenerateOpinion}
        </Button>
      ) : (
        <Button
          variant="primary"
          size="sm"
          isLoading={actionLoading}
          onClick={onGenerate}
          disabled={!analysisHistoryId}
        >
          {text.generateOpinion}
        </Button>
      )}
    >
      {!opinion ? (
        <EmptyState
          title={text.noOpinion}
          description={text.noOpinionDescription}
          action={analysisHistoryId ? (
            <Button variant="primary" size="sm" isLoading={actionLoading} onClick={onGenerate}>
              {text.generateOpinion}
            </Button>
          ) : null}
        />
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={statusBadgeVariant}>{statusLabel}</Badge>
            <Badge variant={opinion.isCurrent ? 'success' : 'default'}>
              {opinion.isCurrent ? text.currentVersion : text.latestVersion}
            </Badge>
            <Badge variant={opinion.sourceStatus === 'deleted' ? 'warning' : 'info'}>
              {opinion.sourceStatus === 'deleted' ? text.sourceUnavailable : text.sourceAvailable}
            </Badge>
            <Badge variant="default">{text.version} {opinion.version}</Badge>
          </div>

          {renderStatusAlert()}

          {opinion.sourceStatus === 'deleted' ? (
            <InlineAlert variant="warning" message={text.sourceDeleted} />
          ) : null}

          {status === 'completed' ? (
            <>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                <div className="rounded-2xl border border-border/60 bg-surface-2/70 p-4">
                  <div className="text-xs uppercase tracking-[0.24em] text-muted-text">{text.generatedAt}</div>
                  <div className="mt-2 text-sm text-foreground">
                    {formatDateTime(opinion.generatedAt || opinion.createdAt)}
                  </div>
                </div>
                <div className="rounded-2xl border border-border/60 bg-surface-2/70 p-4">
                  <div className="text-xs uppercase tracking-[0.24em] text-muted-text">{text.model}</div>
                  <div className="mt-2 text-sm text-foreground">{opinion.model || '—'}</div>
                </div>
                <div className="rounded-2xl border border-border/60 bg-surface-2/70 p-4">
                  <div className="text-xs uppercase tracking-[0.24em] text-muted-text">{text.promptVersion}</div>
                  <div className="mt-2 text-sm text-foreground">{opinion.promptVersion || '—'}</div>
                </div>
              </div>

              <div className="rounded-2xl border border-border/60 bg-surface-2/60 p-4">
                <div className="text-xs uppercase tracking-[0.24em] text-muted-text">{text.summary}</div>
                <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-foreground">{summary || '—'}</p>
              </div>

              <div className="grid gap-4 xl:grid-cols-2">
                <div className="rounded-2xl border border-border/60 bg-surface-2/60 p-4">
                  <div className="text-xs uppercase tracking-[0.24em] text-muted-text">{text.keyFindings}</div>
                  <div className="mt-3">{renderStringList(keyFindings)}</div>
                </div>
                <div className="rounded-2xl border border-border/60 bg-surface-2/60 p-4">
                  <div className="text-xs uppercase tracking-[0.24em] text-muted-text">{text.supportingEvidence}</div>
                  <div className="mt-3">{renderStringList(supportingEvidence)}</div>
                </div>
                <div className="rounded-2xl border border-border/60 bg-surface-2/60 p-4">
                  <div className="text-xs uppercase tracking-[0.24em] text-muted-text">{text.risks}</div>
                  <div className="mt-3">{renderStringList(risks)}</div>
                </div>
                <div className="rounded-2xl border border-border/60 bg-surface-2/60 p-4">
                  <div className="text-xs uppercase tracking-[0.24em] text-muted-text">{text.uncertainties}</div>
                  <div className="mt-3">{renderStringList(uncertainties)}</div>
                </div>
                <div className="rounded-2xl border border-border/60 bg-surface-2/60 p-4">
                  <div className="text-xs uppercase tracking-[0.24em] text-muted-text">{text.limitations}</div>
                  <div className="mt-3">{renderStringList(limitations)}</div>
                </div>
                <div className="rounded-2xl border border-border/60 bg-surface-2/60 p-4">
                  <div className="text-xs uppercase tracking-[0.24em] text-muted-text">{text.thingsToWatch}</div>
                  <div className="mt-3">{renderStringList(watchItems)}</div>
                </div>
              </div>

              <div className="grid gap-4 xl:grid-cols-2">
                <div className="rounded-2xl border border-border/60 bg-surface-2/60 p-4">
                  <div className="text-xs uppercase tracking-[0.24em] text-muted-text">{text.disciplineNotes}</div>
                  <div className="mt-3">{renderStringList(disciplineNotes)}</div>
                </div>
                <div className="rounded-2xl border border-border/60 bg-surface-2/60 p-4">
                  <div className="text-xs uppercase tracking-[0.24em] text-muted-text">{text.disclaimer}</div>
                  <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-secondary-text">
                    {disclaimer || '—'}
                  </p>
                </div>
              </div>
            </>
          ) : null}
        </div>
      )}
    </SectionCard>
  );
};
