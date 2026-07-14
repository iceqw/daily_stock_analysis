export type PrincipleAssessmentStatus = 'aligned' | 'at_risk' | 'violated' | 'not_applicable' | 'insufficient_evidence';

export interface PrincipleAssessment {
  principle_id: number;
  principle_version: number;
  category: string;
  severity: string;
  title: string;
  assessment_status: PrincipleAssessmentStatus | null;
  evidence?: Array<{ statement?: string; source_ref?: string | null }> | null;
  explanation?: string | null;
  confidence?: number | null;
}

const STATUS_LABEL: Record<PrincipleAssessmentStatus, string> = {
  aligned: '符合', at_risk: '存在风险', violated: '疑似违反',
  not_applicable: '不适用', insufficient_evidence: '证据不足',
};

export function PrincipleAssessments({ refs }: { refs: PrincipleAssessment[] }) {
  if (!refs.length) return <p className="text-sm text-slate-500">本次无有效原则可评估</p>;
  return (
    <section aria-label="投资原则检查" className="space-y-3">
      <h3 className="text-base font-semibold">投资原则检查</h3>
      {refs.map((ref) => (
        <article key={`${ref.principle_id}:${ref.principle_version}`} className="rounded border p-3">
          <div className="flex items-center justify-between gap-2">
            <h4 className="font-medium">{ref.title}</h4>
            <span>{ref.assessment_status ? STATUS_LABEL[ref.assessment_status] : '待评估'}</span>
          </div>
          <p className="text-xs text-slate-500">v{ref.principle_version} · {ref.category} · {ref.severity}</p>
          {ref.explanation && <p className="mt-2 text-sm">{ref.explanation}</p>}
          {ref.evidence?.length ? (
            <ul className="mt-2 list-disc pl-5 text-sm">
              {ref.evidence.map((evidence, index) => <li key={`${evidence.source_ref ?? 'derived'}:${index}`}>{evidence.statement}</li>)}
            </ul>
          ) : null}
          {ref.confidence != null && <p className="mt-2 text-xs text-slate-500">置信度：{Math.round(ref.confidence * 100)}%</p>}
        </article>
      ))}
    </section>
  );
}

export default PrincipleAssessments;
