import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AIOpinionPanel } from '../AIOpinionPanel';
import { aiOpinionsApi, type AIOpinionDetail, type AIOpinionListItem } from '../../../api/aiOpinions';

vi.mock('../../../api/aiOpinions', () => ({
  aiOpinionsApi: { listByAnalysisHistory: vi.fn(), get: vi.fn(), generate: vi.fn(), retry: vi.fn(), regenerate: vi.fn() },
}));

const api = vi.mocked(aiOpinionsApi);

const listItem = (overrides: Partial<AIOpinionListItem> = {}): AIOpinionListItem => ({
  id: 1, analysisHistoryId: 42, analysisHistoryAvailable: true, version: 1, isCurrent: true,
  sourceStatus: 'available', generationStatus: 'completed', retryCount: 0, ...overrides,
});

const detail = (item: AIOpinionListItem = listItem()): AIOpinionDetail => ({
  ...item,
  content: 'Summary from detail',
  outputJson: {
    summary: 'Summary from output', keyFindings: ['Finding'], supportingEvidence: ['Support'],
    risks: ['Risk'], uncertainties: ['Uncertainty'], limitations: ['Limitation'],
    thingsToWatch: ['Watch'], investmentDisciplineNotes: ['Discipline note'],
    overallDisciplineSummary: 'Discipline summary', disclaimer: 'Not financial advice',
    principle_snapshot_json: 'must not render', system_prompt: 'must not render',
  },
  principleRefs: [{ principleId: 1, principleVersion: 2, category: 'risk', severity: 'hard', title: 'Capital protection', assessmentStatus: 'aligned', explanation: 'Aligned' }],
  provider: 'provider-x', model: 'model-x', createdAt: '2026-07-14T01:00:00Z', generatedAt: '2026-07-14T01:01:00Z',
});

const listResponse = (items: AIOpinionListItem[]) => ({ items, total: items.length, page: 1, pageSize: 100 });
const accepted = (opinion: AIOpinionDetail) => ({ opinion, accepted: true, taskId: 'task', traceId: 'trace', taskStatus: 'pending' });

describe('AIOpinionPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listByAnalysisHistory.mockResolvedValue(listResponse([]));
    api.get.mockImplementation(async (id) => detail(listItem({ id })));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('offers manual generation when no opinion exists and prevents rapid duplicate requests', async () => {
    const pending = detail(listItem({ id: 2, version: 1, generationStatus: 'pending' }));
    api.generate.mockResolvedValue(accepted(pending));
    render(<AIOpinionPanel analysisHistoryId={42} />);
    const button = await screen.findByRole('button', { name: 'Generate AI Opinion' });
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(api.generate).toHaveBeenCalledTimes(1));
  });

  it('loads the selected detail separately from the list and renders principle assessments', async () => {
    const item = listItem({ id: 7 });
    api.listByAnalysisHistory.mockResolvedValue(listResponse([item]));
    api.get.mockResolvedValue(detail(item));
    render(<AIOpinionPanel analysisHistoryId={42} />);
    expect(await screen.findByText('Capital protection')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith(7);
    expect(screen.getByText('Finding')).toBeInTheDocument();
    expect(screen.getByText('Uncertainty')).toBeInTheDocument();
    expect(screen.getByText('Limitation')).toBeInTheDocument();
    expect(screen.getByText('Discipline summary')).toBeInTheDocument();
    expect(screen.getByText('Not financial advice')).toBeInTheDocument();
    expect(screen.queryByText(/must not render/)).not.toBeInTheDocument();
  });

  it('keeps the version selector available for pending, failed, and rejected versions', async () => {
    const pending = listItem({ id: 2, version: 2, generationStatus: 'pending', isCurrent: false });
    const failed = listItem({ id: 3, version: 3, generationStatus: 'failed', isCurrent: false });
    api.listByAnalysisHistory.mockResolvedValue(listResponse([pending, failed]));
    render(<AIOpinionPanel analysisHistoryId={42} />);
    const selector = await screen.findByRole('combobox', { name: 'Opinion version' });
    expect(selector).toBeInTheDocument();
    fireEvent.change(selector, { target: { value: '3' } });
    expect(await screen.findByText('Generation failed')).toBeInTheDocument();
    fireEvent.change(selector, { target: { value: '2' } });
    expect(await screen.findByText('Queued for generation')).toBeInTheDocument();
  });

  it('targets the selected failed version for retry and the selected completed version for regenerate', async () => {
    const completed = listItem({ id: 1, version: 1, generationStatus: 'completed', isCurrent: true });
    const failed = listItem({ id: 2, version: 2, generationStatus: 'failed', isCurrent: false });
    api.listByAnalysisHistory.mockResolvedValue(listResponse([failed, completed]));
    api.retry.mockResolvedValue(accepted(detail(listItem({ ...failed, generationStatus: 'pending' }))));
    api.regenerate.mockResolvedValue(accepted(detail(listItem({ id: 3, version: 3, generationStatus: 'pending', isCurrent: false }))));
    render(<AIOpinionPanel analysisHistoryId={42} />);
    const selector = await screen.findByRole('combobox', { name: 'Opinion version' });
    fireEvent.change(selector, { target: { value: '2' } });
    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(api.retry).toHaveBeenCalledWith(2));
  });

  it('targets the selected completed version for regenerate', async () => {
    const completed = listItem({ id: 9, version: 4, generationStatus: 'completed', isCurrent: true });
    api.listByAnalysisHistory.mockResolvedValue(listResponse([completed]));
    api.regenerate.mockResolvedValue(accepted(detail(listItem({ id: 10, version: 5, generationStatus: 'pending', isCurrent: false }))));
    render(<AIOpinionPanel analysisHistoryId={42} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Regenerate' }));
    await waitFor(() => expect(api.regenerate).toHaveBeenCalledWith(9));
  });

  it('continues polling a new non-current version while an old current version is completed', async () => {
    vi.useFakeTimers();
    const oldCurrent = listItem({ id: 1, version: 1, generationStatus: 'completed', isCurrent: true });
    const pending = listItem({ id: 2, version: 2, generationStatus: 'pending', isCurrent: false });
    api.listByAnalysisHistory.mockResolvedValueOnce(listResponse([oldCurrent])).mockResolvedValueOnce(listResponse([pending, oldCurrent]));
    api.regenerate.mockResolvedValue(accepted(detail(pending)));
    api.get.mockResolvedValue(detail(oldCurrent));
    render(<AIOpinionPanel analysisHistoryId={42} />);
    await vi.waitFor(() => expect(screen.getByRole('button', { name: 'Regenerate' })).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Regenerate' }));
    await vi.waitFor(() => expect(api.regenerate).toHaveBeenCalledWith(1));
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(api.listByAnalysisHistory).toHaveBeenCalledTimes(2);
  });

  it('refreshes the completed detail after polling observes a terminal state and stops on errors', async () => {
    vi.useFakeTimers();
    const pending = listItem({ id: 2, version: 2, generationStatus: 'pending', isCurrent: false });
    const completed = listItem({ id: 2, version: 2, generationStatus: 'completed', isCurrent: true });
    api.listByAnalysisHistory.mockResolvedValueOnce(listResponse([pending])).mockResolvedValueOnce(listResponse([completed]));
    api.get.mockResolvedValue(detail(completed));
    render(<AIOpinionPanel analysisHistoryId={42} />);
    await act(async () => { await Promise.resolve(); vi.advanceTimersByTime(3000); await Promise.resolve(); });
    expect(api.get).toHaveBeenCalledWith(2);
    expect(api.listByAnalysisHistory).toHaveBeenCalledTimes(2);
  });

  it('stops polling when the request fails and cleans up on unmount', async () => {
    vi.useFakeTimers();
    const pending = listItem({ id: 2, generationStatus: 'pending' });
    api.listByAnalysisHistory.mockResolvedValueOnce(listResponse([pending])).mockRejectedValueOnce(new Error('poll failed'));
    const view = render(<AIOpinionPanel analysisHistoryId={42} />);
    await vi.waitFor(() => expect(screen.getByText('Queued for generation')).toBeInTheDocument());
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    await vi.waitFor(() => expect(screen.getByText('poll failed')).toBeInTheDocument());
    view.unmount();
    await act(async () => { vi.advanceTimersByTime(6000); });
    expect(api.listByAnalysisHistory).toHaveBeenCalledTimes(2);
  });
});
