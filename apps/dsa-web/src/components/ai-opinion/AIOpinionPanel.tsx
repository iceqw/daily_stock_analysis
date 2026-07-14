import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { aiOpinionsApi, type AIOpinionDetail, type AIOpinionGenerationStatus, type AIOpinionListItem } from '../../api/aiOpinions';
import { getParsedApiError, type ParsedApiError } from '../../api/error';
import { Button, Card, InlineAlert } from '../common';
import { PrincipleAssessments } from './PrincipleAssessments';

const POLL_INTERVAL_MS = 3000;
const IN_FLIGHT_STATUSES = new Set<AIOpinionGenerationStatus>(['pending', 'generating']);

const statusLabel: Record<AIOpinionGenerationStatus, string> = {
  pending: 'Queued for generation', generating: 'AI Opinion is generating', completed: 'Completed',
  failed: 'Generation failed', rejected: 'Generation rejected',
};

const isInFlight = (opinion?: AIOpinionListItem | null): boolean => Boolean(opinion && IN_FLIGHT_STATUSES.has(opinion.generationStatus));

const latestByVersion = (items: AIOpinionListItem[]): AIOpinionListItem | null => [...items]
  .sort((left, right) => right.version - left.version || (right.createdAt || '').localeCompare(left.createdAt || ''))[0] || null;

const latestInFlight = (items: AIOpinionListItem[]): AIOpinionListItem | null => latestByVersion(items.filter((item) => isInFlight(item)));

const asStrings = (value: unknown): string[] => {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item === 'string' && item.trim()) return [item];
    if (typeof item === 'object' && item !== null && 'statement' in item && typeof item.statement === 'string') return [item.statement];
    return [];
  });
};

const outputValue = (detail: AIOpinionDetail, ...keys: string[]): unknown => {
  for (const key of keys) {
    if (detail.outputJson && detail.outputJson[key] !== undefined) return detail.outputJson[key];
  }
  return undefined;
};

const ListSection: React.FC<{ title: string; values: string[] }> = ({ title, values }) => values.length ? (
  <section>
    <h4 className="text-sm font-semibold text-foreground">{title}</h4>
    <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-secondary-text">
      {values.map((value, index) => <li key={`${value}:${index}`}>{value}</li>)}
    </ul>
  </section>
) : null;

export const AIOpinionPanel: React.FC<{ analysisHistoryId: number }> = ({ analysisHistoryId }) => {
  const [opinions, setOpinions] = useState<AIOpinionListItem[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<AIOpinionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [detailError, setDetailError] = useState<ParsedApiError | null>(null);
  const pollTimerRef = useRef<number | null>(null);
  const viewGenerationRef = useRef(0);
  const listRequestRef = useRef(0);
  const detailRequestRef = useRef(0);
  const refreshListRef = useRef<((showLoading: boolean, generation: number, fromPolling?: boolean) => Promise<void>) | null>(null);
  const selectedIdRef = useRef<number | null>(null);
  const inFlightRef = useRef<AIOpinionListItem | null>(null);
  const actionInFlightRef = useRef(false);
  const actionRequestRef = useRef(0);
  const currentHistoryIdRef = useRef(analysisHistoryId);
  currentHistoryIdRef.current = analysisHistoryId;

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current !== null) {
      window.clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const selectDefaultId = useCallback((items: AIOpinionListItem[]): number | null => {
    const preferred = latestInFlight(items) || items.find((item) => item.isCurrent) || latestByVersion(items);
    return preferred?.id ?? null;
  }, []);

  const loadDetail = useCallback(async (opinionId: number, generation = viewGenerationRef.current) => {
    const request = ++detailRequestRef.current;
    setDetailLoading(true);
    setDetailError(null);
    try {
      const detail = await aiOpinionsApi.get(opinionId);
      if (generation !== viewGenerationRef.current || request !== detailRequestRef.current || selectedIdRef.current !== opinionId) return;
      setSelectedDetail(detail);
    } catch (err) {
      if (generation === viewGenerationRef.current && request === detailRequestRef.current && selectedIdRef.current === opinionId) {
        setDetailError(getParsedApiError(err));
        setSelectedDetail(null);
      }
    } finally {
      if (generation === viewGenerationRef.current && request === detailRequestRef.current) setDetailLoading(false);
    }
  }, []);

  const schedulePoll = useCallback((generation: number) => {
    stopPolling();
    pollTimerRef.current = window.setTimeout(() => {
      pollTimerRef.current = null;
      void refreshListRef.current?.(false, generation, true);
    }, POLL_INTERVAL_MS);
  }, [stopPolling]);

  const refreshList = useCallback(async (showLoading: boolean, generation: number, fromPolling = false) => {
    if (generation !== viewGenerationRef.current) return;
    const request = ++listRequestRef.current;
    if (showLoading) setLoading(true);
    try {
      const response = await aiOpinionsApi.listByAnalysisHistory(analysisHistoryId);
      if (generation !== viewGenerationRef.current || request !== listRequestRef.current) return;
      const previousInFlight = inFlightRef.current;
      const nextInFlight = latestInFlight(response.items);
      setOpinions(response.items);
      inFlightRef.current = nextInFlight;
      const selectedStillExists = selectedIdRef.current !== null && response.items.some((item) => item.id === selectedIdRef.current);
      if (!selectedStillExists) {
        const nextId = selectDefaultId(response.items);
        selectedIdRef.current = nextId;
        setSelectedId(nextId);
        setSelectedDetail(null);
      }
      setError(null);
      if (fromPolling && previousInFlight && !isInFlight(response.items.find((item) => item.id === previousInFlight.id))) {
        void loadDetail(previousInFlight.id, generation);
      }
      if (nextInFlight) schedulePoll(generation);
    } catch (err) {
      if (generation === viewGenerationRef.current && request === listRequestRef.current) {
        setError(getParsedApiError(err));
        stopPolling();
      }
    } finally {
      if (generation === viewGenerationRef.current && request === listRequestRef.current) setLoading(false);
    }
  }, [analysisHistoryId, loadDetail, schedulePoll, selectDefaultId, stopPolling]);

  refreshListRef.current = refreshList;

  useEffect(() => {
    const generation = ++viewGenerationRef.current;
    actionRequestRef.current += 1;
    actionInFlightRef.current = false;
    setSubmitting(false);
    stopPolling();
    selectedIdRef.current = null;
    inFlightRef.current = null;
    setSelectedId(null);
    setSelectedDetail(null);
    setOpinions([]);
    void refreshList(true, generation);
    return () => {
      viewGenerationRef.current += 1;
      stopPolling();
    };
  }, [analysisHistoryId, refreshList, stopPolling]);

  useEffect(() => {
    if (selectedId === null) return;
    selectedIdRef.current = selectedId;
    setSelectedDetail(null);
    void loadDetail(selectedId);
  }, [loadDetail, selectedId]);

  const selectedOpinion = useMemo(() => opinions.find((item) => item.id === selectedId) || null, [opinions, selectedId]);
  const inFlightOpinion = useMemo(() => latestInFlight(opinions), [opinions]);
  const operationsDisabled = submitting || Boolean(inFlightOpinion) || selectedOpinion?.sourceStatus === 'deleted' || selectedOpinion?.analysisHistoryAvailable === false;

  const startAction = useCallback(async (action: 'generate' | 'retry' | 'regenerate') => {
    if (actionInFlightRef.current || operationsDisabled) return;
    const targetId = selectedOpinion?.id;
    if ((action === 'retry' || action === 'regenerate') && targetId === undefined) return;
    const generation = viewGenerationRef.current;
    const historyId = analysisHistoryId;
    const requestId = ++actionRequestRef.current;
    const isCurrentAction = () => generation === viewGenerationRef.current
      && historyId === currentHistoryIdRef.current
      && requestId === actionRequestRef.current;
    actionInFlightRef.current = true;
    setSubmitting(true);
    setError(null);
    try {
      const accepted = action === 'generate'
        ? await aiOpinionsApi.generate(analysisHistoryId)
        : action === 'retry'
          ? await aiOpinionsApi.retry(targetId as number)
          : await aiOpinionsApi.regenerate(targetId as number);
      if (!isCurrentAction()) return;
      const nextListItem: AIOpinionListItem = accepted.opinion;
      setOpinions((current) => [nextListItem, ...current.filter((item) => item.id !== nextListItem.id)]);
      inFlightRef.current = nextListItem;
      selectedIdRef.current = nextListItem.id;
      setSelectedId(nextListItem.id);
      setSelectedDetail(accepted.opinion);
      schedulePoll(generation);
    } catch (err) {
      if (isCurrentAction()) setError(getParsedApiError(err));
    } finally {
      if (isCurrentAction()) {
        actionInFlightRef.current = false;
        setSubmitting(false);
      }
    }
  }, [analysisHistoryId, currentHistoryIdRef, operationsDisabled, schedulePoll, selectedOpinion]);

  if (loading) return <Card padding="md"><p className="text-sm text-secondary-text">Loading AI Opinion...</p></Card>;
  if (error && !opinions.length) return <Card padding="md"><InlineAlert variant="danger" title="AI Opinion unavailable" message={error.message} action={<Button variant="secondary" size="sm" onClick={() => void refreshList(true, viewGenerationRef.current)}>Retry</Button>} /></Card>;

  const selectedStatus = selectedOpinion?.generationStatus;
  const detail = selectedDetail && selectedDetail.id === selectedId ? selectedDetail : null;
  const detailOutput = detail || ({ outputJson: {} } as AIOpinionDetail);
  const structuredSummaryValue = outputValue(detailOutput, 'summary');
  const structuredSummary = typeof structuredSummaryValue === 'string'
    ? structuredSummaryValue
    : typeof detail?.conclusion === 'string' ? detail.conclusion : null;
  const legacyContent = structuredSummary ? null : detail?.content || null;
  const showStructuredSections = Boolean(structuredSummary);
  const keyFindings = asStrings(outputValue(detailOutput, 'keyFindings', 'key_findings'));
  const supportingEvidence = detail?.evidence?.map((item) => item.statement || '').filter(Boolean) || asStrings(outputValue(detailOutput, 'supportingEvidence', 'supporting_evidence'));
  const risks = detail?.risks || asStrings(outputValue(detailOutput, 'risks'));
  const uncertainties = asStrings(outputValue(detailOutput, 'uncertainties'));
  const limitations = detail?.limitations || asStrings(outputValue(detailOutput, 'limitations'));
  const thingsToWatch = detail?.watchItems || asStrings(outputValue(detailOutput, 'thingsToWatch', 'things_to_watch'));
  const disciplineNotes = asStrings(outputValue(detailOutput, 'investmentDisciplineNotes', 'investment_discipline_notes'));
  const disciplineSummary = outputValue(detailOutput, 'overallDisciplineSummary', 'overall_discipline_summary');
  const disclaimer = outputValue(detailOutput, 'disclaimer');
  const unavailableReason = selectedOpinion?.sourceStatus === 'deleted'
    ? 'The analysis source has been deleted; this version is read-only.'
    : selectedOpinion?.analysisHistoryAvailable === false
      ? 'The linked analysis history is unavailable; this version is read-only.'
      : null;

  return <Card padding="md" className="space-y-4" data-testid="ai-opinion-panel">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h2 className="text-xl font-semibold text-foreground">AI Opinion</h2><p className="mt-1 text-sm text-secondary-text">Versioned opinion for this analysis</p></div>
      <div className="flex flex-wrap gap-2">
        {!opinions.length ? <Button size="sm" onClick={() => void startAction('generate')} isLoading={submitting} disabled={operationsDisabled}>Generate AI Opinion</Button> : null}
        {selectedStatus === 'completed' ? <Button size="sm" variant="secondary" onClick={() => void startAction('regenerate')} isLoading={submitting} disabled={operationsDisabled}>Regenerate</Button> : null}
        {selectedStatus === 'failed' || selectedStatus === 'rejected' ? <Button size="sm" onClick={() => void startAction('retry')} isLoading={submitting} disabled={operationsDisabled}>Retry</Button> : null}
      </div>
    </div>
    {error ? <InlineAlert variant="danger" title="Request failed" message={error.message} /> : null}
    {unavailableReason ? <p className="text-sm text-secondary-text">{unavailableReason}</p> : null}
    {opinions.length > 1 ? <label className="block text-sm text-secondary-text">Opinion version<select className="input mt-1 block w-full max-w-xs" value={selectedId ?? ''} onChange={(event) => setSelectedId(Number(event.target.value))}>{opinions.map((item) => <option key={item.id} value={item.id}>v{item.version}{item.isCurrent ? ' · Current' : ''} · {item.generationStatus}</option>)}</select></label> : null}
    {!selectedOpinion ? <p className="rounded-lg border border-dashed border-border p-4 text-sm text-secondary-text">No AI Opinion has been generated yet.</p> : <>
      <div className="flex flex-wrap items-center gap-2 text-sm"><span className="rounded-full border border-primary/30 bg-primary/10 px-2.5 py-1 text-primary">{statusLabel[selectedStatus!]}</span><span className="text-secondary-text">Version {selectedOpinion.version}{selectedOpinion.isCurrent ? ' · Current' : ''}</span></div>
      {detailError ? <InlineAlert variant="danger" title="Opinion details unavailable" message={detailError.message} action={<Button variant="secondary" size="sm" onClick={() => void loadDetail(selectedOpinion.id)}>Retry</Button>} /> : null}
      {detailLoading ? <p className="text-sm text-secondary-text">Loading opinion details...</p> : null}
      {selectedStatus === 'pending' ? <p className="text-sm text-secondary-text">The opinion has entered the generation queue.</p> : null}
      {selectedStatus === 'generating' ? <p className="text-sm text-secondary-text">Please wait while the opinion is generated.</p> : null}
      {selectedStatus === 'failed' || selectedStatus === 'rejected' ? <p className="text-sm text-danger">{detail?.errorMessage || selectedOpinion.errorMessage || (selectedStatus === 'rejected' ? 'The output was rejected by validation or safety checks.' : 'The generation request failed.')}</p> : null}
      {selectedStatus === 'completed' && detail ? <div className="space-y-4">
        {structuredSummary ? <p className="whitespace-pre-wrap text-sm leading-6 text-foreground">{structuredSummary}</p> : null}
        {legacyContent ? <p className="whitespace-pre-wrap text-sm leading-6 text-foreground">{legacyContent}</p> : null}
        {showStructuredSections ? <>
          <ListSection title="Key findings" values={keyFindings} />
          <ListSection title="Supporting evidence" values={supportingEvidence} />
          <ListSection title="Risks" values={risks} />
          <ListSection title="Uncertainties" values={uncertainties} />
          <ListSection title="Limitations" values={limitations} />
          <ListSection title="Things to watch" values={thingsToWatch} />
          <ListSection title="Investment discipline notes" values={disciplineNotes} />
          {typeof disciplineSummary === 'string' ? <p className="text-sm text-secondary-text"><strong>Overall discipline summary:</strong> {disciplineSummary}</p> : null}
          {typeof disclaimer === 'string' ? <p className="text-xs text-muted-text"><strong>Disclaimer:</strong> {disclaimer}</p> : null}
        </> : null}
        {showStructuredSections ? <PrincipleAssessments refs={detail.principleRefs.map((ref) => ({
          principle_id: ref.principleId, principle_version: ref.principleVersion, category: ref.category,
          severity: ref.severity, title: ref.title, assessment_status: ref.assessmentStatus,
          evidence: ref.evidence?.map((item) => ({ statement: item.statement, source_ref: item.sourceRef })),
          explanation: ref.explanation, confidence: ref.confidence,
        }))} /> : null}
        <p className="text-xs text-muted-text">Provider: {detail.provider || '--'} · Model: {detail.model || '--'} · Version {detail.version}{detail.isCurrent ? ' · Current' : ''}</p>
        <p className="text-xs text-muted-text">Created: {detail.createdAt || '--'} · Generated: {detail.generatedAt || '--'}</p>
      </div> : null}
    </>}
  </Card>;
};

export default AIOpinionPanel;
