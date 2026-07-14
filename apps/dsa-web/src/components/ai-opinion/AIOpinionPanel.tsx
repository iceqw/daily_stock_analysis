import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { aiOpinionsApi, type AIOpinionDetail, type AIOpinionGenerationStatus } from '../../api/aiOpinions';
import { getParsedApiError, type ParsedApiError } from '../../api/error';
import { Button, Card, InlineAlert } from '../common';
import { PrincipleAssessments } from './PrincipleAssessments';

const POLL_INTERVAL_MS = 3000;
const IN_FLIGHT = new Set<AIOpinionGenerationStatus>(['pending', 'generating']);

const statusLabel: Record<AIOpinionGenerationStatus, string> = {
  pending: 'Queued for generation', generating: 'AI Opinion is generating', completed: 'Completed',
  failed: 'Generation failed', rejected: 'Generation rejected',
};

const asList = (value: unknown): string[] => Array.isArray(value)
  ? value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
  : [];

const outputValue = (opinion: AIOpinionDetail, key: string): unknown => opinion.outputJson?.[key];

const ListSection: React.FC<{ title: string; values: string[] }> = ({ title, values }) => values.length ? (
  <section>
    <h4 className="text-sm font-semibold text-foreground">{title}</h4>
    <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-secondary-text">
      {values.map((value, index) => <li key={`${value}:${index}`}>{value}</li>)}
    </ul>
  </section>
) : null;

export const AIOpinionPanel: React.FC<{ analysisHistoryId: number }> = ({ analysisHistoryId }) => {
  const [opinions, setOpinions] = useState<AIOpinionDetail[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const pollTimer = useRef<number | null>(null);

  const stopPolling = useCallback(() => {
    if (pollTimer.current !== null) {
      window.clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  const load = useCallback(async (showLoading = false) => {
    if (showLoading) setLoading(true);
    try {
      const response = await aiOpinionsApi.listByAnalysisHistory(analysisHistoryId);
      setOpinions(response.items);
      setSelectedId((current) => current && response.items.some((item) => item.id === current)
        ? current
        : response.items.find((item) => item.isCurrent)?.id ?? response.items[0]?.id ?? null);
      setError(null);
      return response.items;
    } catch (err) {
      setError(getParsedApiError(err));
      return [];
    } finally {
      setLoading(false);
    }
  }, [analysisHistoryId]);

  useEffect(() => {
    stopPolling();
    void load(true);
    return stopPolling;
  }, [analysisHistoryId, load, stopPolling]);

  const current = useMemo(() => opinions.find((item) => item.id === selectedId) ?? null, [opinions, selectedId]);
  const active = useMemo(() => opinions.find((item) => item.isCurrent) ?? opinions[0] ?? null, [opinions]);

  useEffect(() => {
    stopPolling();
    if (!active || !IN_FLIGHT.has(active.generationStatus)) return undefined;
    pollTimer.current = window.setInterval(() => void load(), POLL_INTERVAL_MS);
    return stopPolling;
  }, [active, load, stopPolling]);

  const runAction = useCallback(async (action: 'generate' | 'retry' | 'regenerate', opinionId?: number) => {
    if (submitting || (active && IN_FLIGHT.has(active.generationStatus))) return;
    setSubmitting(true);
    setError(null);
    try {
      const response = action === 'generate'
        ? await aiOpinionsApi.generate(analysisHistoryId)
        : action === 'retry'
          ? await aiOpinionsApi.retry(opinionId as number)
          : await aiOpinionsApi.regenerate(opinionId as number);
      setOpinions((items) => [response.opinion, ...items.filter((item) => item.id !== response.opinion.id)]);
      setSelectedId(response.opinion.id);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setSubmitting(false);
    }
  }, [active, analysisHistoryId, submitting]);

  if (loading) return <Card padding="md"><p className="text-sm text-secondary-text">Loading AI Opinion...</p></Card>;
  if (error && !opinions.length) return <Card padding="md"><InlineAlert variant="danger" title="AI Opinion unavailable" message={error.message} action={<Button variant="secondary" size="sm" onClick={() => void load(true)}>Retry</Button>} /></Card>;

  const status = current?.generationStatus;
  const summary = typeof outputValue(current || active || {} as AIOpinionDetail, 'summary') === 'string'
    ? outputValue(current || active || {} as AIOpinionDetail, 'summary') as string
    : null;
  const content = current?.content || summary;
  const keyFindings = asList(outputValue(current || active || {} as AIOpinionDetail, 'key_findings') ?? outputValue(current || active || {} as AIOpinionDetail, 'keyFindings'));
  const risks = current?.risks || asList(outputValue(current || active || {} as AIOpinionDetail, 'risks'));
  const watchItems = current?.watchItems || asList(outputValue(current || active || {} as AIOpinionDetail, 'things_to_watch') ?? outputValue(current || active || {} as AIOpinionDetail, 'thingsToWatch'));

  return <Card padding="md" className="space-y-4" data-testid="ai-opinion-panel">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h2 className="text-xl font-semibold text-foreground">AI Opinion</h2><p className="mt-1 text-sm text-secondary-text">Versioned opinion for this analysis</p></div>
      <div className="flex flex-wrap gap-2">
        {!active ? <Button size="sm" onClick={() => void runAction('generate')} isLoading={submitting}>Generate AI Opinion</Button> : null}
        {active && status === 'completed' ? <Button size="sm" variant="secondary" onClick={() => void runAction('regenerate', active.id)} isLoading={submitting}>Regenerate</Button> : null}
        {active && (status === 'failed' || status === 'rejected') ? <Button size="sm" onClick={() => void runAction('retry', active.id)} isLoading={submitting}>Retry</Button> : null}
      </div>
    </div>
    {error ? <InlineAlert variant="danger" title="Request failed" message={error.message} /> : null}
    {!current ? <p className="rounded-lg border border-dashed border-border p-4 text-sm text-secondary-text">No AI Opinion has been generated yet.</p> : <>
      <div className="flex flex-wrap items-center gap-2 text-sm"><span className="rounded-full border border-primary/30 bg-primary/10 px-2.5 py-1 text-primary">{statusLabel[status!]}</span><span className="text-secondary-text">Version {current.version}{current.isCurrent ? ' · Current' : ''}</span></div>
      {status === 'pending' ? <p className="text-sm text-secondary-text">The opinion has entered the generation queue.</p> : null}
      {status === 'generating' ? <p className="text-sm text-secondary-text">Please wait while the opinion is generated.</p> : null}
      {status === 'failed' || status === 'rejected' ? <p className="text-sm text-danger">{current.errorMessage || (status === 'rejected' ? 'The output was rejected by validation or safety checks.' : 'The generation request failed.')}</p> : null}
      {status === 'completed' ? <div className="space-y-4">
        {opinions.length > 1 ? <label className="block text-sm text-secondary-text">Opinion version<select className="input mt-1 block w-full max-w-xs" value={current.id} onChange={(event) => setSelectedId(Number(event.target.value))}>{opinions.map((item) => <option key={item.id} value={item.id}>v{item.version}{item.isCurrent ? ' · Current' : ''} · {item.generationStatus}</option>)}</select></label> : null}
        {content ? <p className="whitespace-pre-wrap text-sm leading-6 text-foreground">{content}</p> : null}
        {current.conclusion && current.conclusion !== content ? <p className="whitespace-pre-wrap text-sm leading-6 text-foreground">{current.conclusion}</p> : null}
        <ListSection title="Key findings" values={keyFindings} />
        <ListSection title="Risks" values={risks} />
        <ListSection title="Things to watch" values={watchItems} />
        <ListSection title="Supporting evidence" values={(current.evidence || []).map((item) => item.statement || '').filter(Boolean)} />
        <PrincipleAssessments refs={current.principleRefs.map((ref) => ({
          principle_id: ref.principleId,
          principle_version: ref.principleVersion,
          category: ref.category,
          severity: ref.severity,
          title: ref.title,
          assessment_status: ref.assessmentStatus,
          evidence: ref.evidence?.map((item) => ({ statement: item.statement, source_ref: item.sourceRef })),
          explanation: ref.explanation,
          confidence: ref.confidence,
        }))} />
        {current.provider || current.model ? <p className="text-xs text-muted-text">Provider: {current.provider || '--'} · Model: {current.model || '--'}</p> : null}
      </div> : null}
    </>}
  </Card>;
};

export default AIOpinionPanel;
