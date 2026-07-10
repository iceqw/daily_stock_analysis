import type React from 'react';
import type { InvestmentJournalEntryItem } from '../../types/investmentJournals';
import { Badge, Button, EmptyState, InlineAlert, SectionCard } from '../common';
import { formatDateTime } from '../../utils/format';
import type { UiLanguage } from '../../i18n/uiText';
import {
  extractStringArray,
  getStockDetailText,
  readStructuredField,
  truncateText,
} from './utils';

interface InvestmentTimelineProps {
  items: InvestmentJournalEntryItem[];
  language: UiLanguage;
  loading?: boolean;
  onCreateManual: () => void;
  onStructure: (entryId: number) => void;
  onRetryStructure: (entryId: number) => void;
  structuringIds?: number[];
}

function renderSimpleList(items: string[]) {
  if (items.length === 0) return <p className="text-sm text-secondary-text">—</p>;
  return (
    <ul className="space-y-2 text-sm text-foreground">
      {items.map((item) => (
        <li key={item} className="flex gap-2">
          <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-purple" />
          <span className="leading-6">{item}</span>
        </li>
      ))}
    </ul>
  );
}

export const InvestmentTimeline: React.FC<InvestmentTimelineProps> = ({
  items,
  language,
  loading = false,
  onCreateManual,
  onStructure,
  onRetryStructure,
  structuringIds = [],
}) => {
  const text = getStockDetailText(language);

  return (
    <SectionCard
      title={text.investmentTimeline}
      subtitle={text.investmentTimelineSubtitle}
      actions={(
        <Button variant="primary" size="sm" onClick={onCreateManual}>
          {text.addJournal}
        </Button>
      )}
    >
      {loading ? (
        <div className="py-8 text-center text-sm text-secondary-text">{text.loading}</div>
      ) : items.length === 0 ? (
        <EmptyState
          title={text.noTimeline}
          description={text.noTimelineDescription}
          action={(
            <Button variant="primary" size="sm" onClick={onCreateManual}>
              {text.addJournal}
            </Button>
          )}
        />
      ) : (
        <div className="space-y-4">
          {items.map((item) => {
            const isManual = item.entryType === 'manual';
            const isStructuring = structuringIds.includes(item.id) || item.aiProcessingStatus === 'pending' || item.aiProcessingStatus === 'processing';
            const structured = item.structuredOutput as Record<string, unknown> | null | undefined;
            const journalSummary = typeof readStructuredField(structured, 'summary') === 'string'
              ? String(readStructuredField(structured, 'summary'))
              : '';
            const journalType = typeof readStructuredField(structured, 'journalType', 'journal_type') === 'string'
              ? String(readStructuredField(structured, 'journalType', 'journal_type'))
              : '';
            const reasons = extractStringArray(readStructuredField(structured, 'reasons'));
            const risks = extractStringArray(readStructuredField(structured, 'risks'));
            const assumptions = extractStringArray(readStructuredField(structured, 'assumptions'));
            const invalidationConditions = extractStringArray(readStructuredField(structured, 'invalidationConditions', 'invalidation_conditions'));
            const emotions = extractStringArray(readStructuredField(structured, 'emotions'));
            const cognitiveBias = extractStringArray(readStructuredField(structured, 'cognitiveBias', 'cognitive_bias'));
            const followUps = extractStringArray(readStructuredField(structured, 'followUpItems', 'follow_up_items'));
            const tags = extractStringArray(readStructuredField(structured, 'tags'));

            return (
              <div key={item.id} className="rounded-3xl border border-border/60 bg-card/70 p-5 shadow-soft-card">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={isManual ? 'history' : 'info'}>
                        {isManual ? text.manualEntry : text.analysisEntry}
                      </Badge>
                      {isManual ? (
                        <Badge
                          variant={
                            item.aiProcessingStatus === 'completed'
                              ? 'success'
                              : item.aiProcessingStatus === 'failed'
                                ? 'danger'
                                : item.aiProcessingStatus === 'not_applicable'
                                  ? 'default'
                                  : 'warning'
                          }
                        >
                          {item.aiProcessingStatus === 'completed'
                            ? text.completed
                            : item.aiProcessingStatus === 'failed'
                              ? text.failed
                              : item.aiProcessingStatus === 'processing'
                                ? text.processing
                                : item.aiProcessingStatus === 'pending'
                                  ? text.pending
                                  : 'N/A'}
                        </Badge>
                      ) : null}
                      <Badge variant={item.sourceStatus === 'deleted' ? 'warning' : 'default'}>
                        {item.sourceStatus === 'deleted' ? text.sourceUnavailable : text.sourceAvailable}
                      </Badge>
                    </div>
                    <div className="mt-3 text-sm text-secondary-text">
                      {formatDateTime(item.createdAt)} · {item.sourceLabel}
                    </div>
                  </div>

                  {isManual ? (
                    <div className="flex items-center gap-2">
                      {item.aiProcessingStatus === 'failed' ? (
                        <Button
                          variant="outline"
                          size="sm"
                          isLoading={isStructuring}
                          onClick={() => onRetryStructure(item.id)}
                        >
                          {text.retryStructuring}
                        </Button>
                      ) : (
                        <Button
                          variant="outline"
                          size="sm"
                          isLoading={isStructuring}
                          onClick={() => onStructure(item.id)}
                          disabled={item.aiProcessingStatus === 'pending' || item.aiProcessingStatus === 'processing'}
                        >
                          {text.aiStructuring}
                        </Button>
                      )}
                    </div>
                  ) : null}
                </div>

                <div className="mt-4 grid gap-4 xl:grid-cols-2">
                  <div className="rounded-2xl border border-border/60 bg-surface-2/60 p-4">
                    <div className="text-xs uppercase tracking-[0.24em] text-muted-text">
                      {isManual ? text.rawContent : text.analysisSummary}
                    </div>
                    <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-foreground">
                      {truncateText(
                        isManual
                          ? item.rawContent
                          : item.summarySnapshot || item.riskSummary || item.currentAiOpinion?.conclusion,
                        280,
                      ) || '—'}
                    </p>
                  </div>

                  <div className="rounded-2xl border border-border/60 bg-surface-2/60 p-4">
                    <div className="text-xs uppercase tracking-[0.24em] text-muted-text">
                      {isManual ? text.structuredResult : text.aiOpinion}
                    </div>
                    {isManual ? (
                      <div className="mt-3 space-y-3">
                        {item.aiProcessingStatus === 'pending' ? (
                          <InlineAlert variant="info" message={text.structuringPending} />
                        ) : null}
                        {item.aiProcessingStatus === 'processing' ? (
                          <InlineAlert variant="info" message={text.structuringProcessing} />
                        ) : null}
                        {item.aiProcessingStatus === 'failed' ? (
                          <InlineAlert variant="danger" message={item.structuredError || text.structuringFailed} />
                        ) : null}
                        {item.aiProcessingStatus === 'completed' && structured ? (
                          <div className="space-y-3 text-sm">
                            <div>
                              <div className="text-xs uppercase tracking-[0.2em] text-muted-text">{text.summary}</div>
                              <p className="mt-1 whitespace-pre-wrap leading-6 text-foreground">{journalSummary || '—'}</p>
                            </div>
                            <div className="grid gap-3 md:grid-cols-2">
                              <div>
                                <div className="text-xs uppercase tracking-[0.2em] text-muted-text">{text.journalType}</div>
                                <p className="mt-1 text-foreground">{journalType || '—'}</p>
                              </div>
                              <div>
                                <div className="text-xs uppercase tracking-[0.2em] text-muted-text">{text.generatedAt}</div>
                                <p className="mt-1 text-foreground">{formatDateTime(item.structuredAt || item.updatedAt)}</p>
                              </div>
                            </div>
                            <div>
                              <div className="text-xs uppercase tracking-[0.2em] text-muted-text">{text.reasons}</div>
                              <div className="mt-2">{renderSimpleList(reasons)}</div>
                            </div>
                            <div>
                              <div className="text-xs uppercase tracking-[0.2em] text-muted-text">{text.risks}</div>
                              <div className="mt-2">{renderSimpleList(risks)}</div>
                            </div>
                            <div className="grid gap-3 md:grid-cols-2">
                              <div>
                                <div className="text-xs uppercase tracking-[0.2em] text-muted-text">{text.assumptions}</div>
                                <div className="mt-2">{renderSimpleList(assumptions)}</div>
                              </div>
                              <div>
                                <div className="text-xs uppercase tracking-[0.2em] text-muted-text">{text.invalidationConditions}</div>
                                <div className="mt-2">{renderSimpleList(invalidationConditions)}</div>
                              </div>
                              <div>
                                <div className="text-xs uppercase tracking-[0.2em] text-muted-text">{text.emotions}</div>
                                <div className="mt-2">{renderSimpleList(emotions)}</div>
                              </div>
                              <div>
                                <div className="text-xs uppercase tracking-[0.2em] text-muted-text">{text.cognitiveBias}</div>
                                <div className="mt-2">{renderSimpleList(cognitiveBias)}</div>
                              </div>
                            </div>
                            <div>
                              <div className="text-xs uppercase tracking-[0.2em] text-muted-text">{text.followUps}</div>
                              <div className="mt-2">{renderSimpleList(followUps)}</div>
                            </div>
                            <div>
                              <div className="text-xs uppercase tracking-[0.2em] text-muted-text">{text.tags}</div>
                              <div className="mt-2">{renderSimpleList(tags)}</div>
                            </div>
                          </div>
                        ) : item.aiProcessingStatus === 'not_applicable' ? (
                          <p className="mt-3 text-sm text-secondary-text">—</p>
                        ) : null}
                      </div>
                    ) : item.currentAiOpinion ? (
                      <div className="mt-3 space-y-3 text-sm">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge
                            variant={
                              item.currentAiOpinion.generationStatus === 'completed'
                                ? 'success'
                                : item.currentAiOpinion.generationStatus === 'failed'
                                  ? 'danger'
                                  : 'warning'
                            }
                          >
                            {item.currentAiOpinion.generationStatus}
                          </Badge>
                          <Badge variant="default">v{item.currentAiOpinion.version}</Badge>
                        </div>
                        <p className="whitespace-pre-wrap leading-6 text-foreground">
                          {truncateText(item.currentAiOpinion.conclusion, 200) || '—'}
                        </p>
                      </div>
                    ) : (
                      <p className="mt-3 text-sm text-secondary-text">{text.noOpinionDescription}</p>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </SectionCard>
  );
};
