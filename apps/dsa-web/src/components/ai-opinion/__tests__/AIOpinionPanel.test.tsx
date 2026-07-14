import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AIOpinionPanel } from '../AIOpinionPanel';
import { aiOpinionsApi } from '../../../api/aiOpinions';

vi.mock('../../../api/aiOpinions', () => ({
  aiOpinionsApi: {
    listByAnalysisHistory: vi.fn(),
    generate: vi.fn(),
    retry: vi.fn(),
    regenerate: vi.fn(),
  },
}));

const api = vi.mocked(aiOpinionsApi);
const completed = {
  id: 1, analysisHistoryId: 42, analysisHistoryAvailable: true, version: 1, isCurrent: true,
  sourceStatus: 'available' as const, generationStatus: 'completed' as const, title: 'Opinion',
  conclusion: 'Hold', outputJson: { summary: 'A concise summary', key_findings: ['Finding one'] },
  evidence: [{ statement: 'Evidence one', sourceRef: 'analysis:42' }], risks: ['Risk one'],
  limitations: [], watchItems: ['Watch one'], model: 'model-x', provider: 'provider-x',
  principleRefs: [{ principleId: 1, principleVersion: 1, category: 'risk', severity: 'hard', title: 'Capital protection', assessmentStatus: 'aligned' as const }], retryCount: 0,
};

describe('AIOpinionPanel', () => {
  beforeEach(() => vi.clearAllMocks());

  it('offers manual generation when no opinion exists', async () => {
    api.listByAnalysisHistory.mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 100 });
    api.generate.mockResolvedValue({ opinion: { ...completed, id: 2, version: 1, generationStatus: 'pending', isCurrent: true }, accepted: true, taskId: 'task', traceId: 'trace', taskStatus: 'pending' });
    render(<AIOpinionPanel analysisHistoryId={42} />);
    expect(await screen.findByText('No AI Opinion has been generated yet.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Generate AI Opinion' }));
    await waitFor(() => expect(api.generate).toHaveBeenCalledWith(42));
    expect(screen.getByText('Queued for generation')).toBeInTheDocument();
  });

  it('renders completed content and principle assessments without snapshot text', async () => {
    api.listByAnalysisHistory.mockResolvedValue({ items: [completed], total: 1, page: 1, pageSize: 100 });
    render(<AIOpinionPanel analysisHistoryId={42} />);
    expect(await screen.findByText('A concise summary')).toBeInTheDocument();
    expect(screen.getByText('Finding one')).toBeInTheDocument();
    expect(screen.getByText('Capital protection')).toBeInTheDocument();
    expect(screen.queryByText(/principle_snapshot_json|prompt_version/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Regenerate' })).toBeInTheDocument();
  });

  it('offers retry for rejected opinions', async () => {
    const rejected = { ...completed, generationStatus: 'rejected' as const, errorMessage: 'Rejected by validator' };
    api.listByAnalysisHistory.mockResolvedValue({ items: [rejected], total: 1, page: 1, pageSize: 100 });
    render(<AIOpinionPanel analysisHistoryId={42} />);
    expect(await screen.findByText('Rejected by validator')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });
});
