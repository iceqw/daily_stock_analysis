import { render, screen } from '@testing-library/react';
import { PrincipleAssessments } from '../PrincipleAssessments';

describe('PrincipleAssessments', () => {
  it('renders the empty principle state', () => {
    render(<PrincipleAssessments refs={[]} />);
    expect(screen.getByText('本次无有效原则可评估')).toBeInTheDocument();
  });

  it('renders assessment metadata and evidence', () => {
    render(<PrincipleAssessments refs={[{
      principle_id: 1, principle_version: 2, category: 'risk', severity: 'hard', title: '证据优先',
      assessment_status: 'insufficient_evidence', explanation: '资料不足', confidence: 0.5,
      evidence: [{ statement: '报告未提供数据', source_ref: 'analysis:1' }],
    }]} />);
    expect(screen.getByRole('heading', { name: '投资原则检查' })).toBeInTheDocument();
    expect(screen.getByText('证据不足')).toBeInTheDocument();
    expect(screen.getByText('报告未提供数据')).toBeInTheDocument();
  });
});
