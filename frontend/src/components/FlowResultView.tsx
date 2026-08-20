import type { FlowResult } from '../api/types'
import EvidenceList from './EvidenceList'
import { classificationLabel } from '../api/labels'

// Renders a FlowResult: the overall Conflict classification, each deterministic finding
// with both sides of its Evidence, and the tracked actions. No paraphrasing into a
// medical/safety verdict — evidence and the classification note are shown verbatim.
export default function FlowResultView({ result }: { result: FlowResult }) {
  const overall = classificationLabel(result.classification)

  return (
    <div className="flow-result">
      <div className={`classification tone-${overall.tone}`}>
        <span className="classification-title">判定: {overall.title}</span>
        {overall.note && <p className="classification-note">{overall.note}</p>}
      </div>

      <h4>Findings（根拠つき）</h4>
      {result.findings.length === 0 ? (
        <p className="muted">検出された findings はありません。（※安全の断定ではありません）</p>
      ) : (
        <ul className="findings">
          {result.findings.map((f, i) => {
            const cls = typeof f.classification === 'string' ? f.classification : undefined
            const label = classificationLabel(cls ? cls.toLowerCase() : undefined)
            const rule = typeof f.rule === 'string' ? f.rule : ''
            const reason = typeof f.reason === 'string' ? f.reason : ''
            const school = Array.isArray(f.school_evidence) ? (f.school_evidence as string[]) : []
            const personal = Array.isArray(f.personal_context_evidence)
              ? (f.personal_context_evidence as string[])
              : []
            return (
              <li key={i} className={`finding card tone-${label.tone}`}>
                <div className="finding-head">
                  <span className="badge">{label.title}</span>
                  {rule && <code className="rule">{rule}</code>}
                </div>
                {reason && <p className="reason">{reason}</p>}
                <EvidenceList label="学校文書の根拠" items={school} />
                <EvidenceList label="登録文脈の根拠" items={personal} />
              </li>
            )
          })}
        </ul>
      )}

      <h4>Actions（トラッキング中）</h4>
      {result.actions.length === 0 ? (
        <p className="muted">作成された action はありません。</p>
      ) : (
        <ul className="actions-list">
          {result.actions.map((a) => (
            <li key={a.action_id} className="action card">
              <div className="action-head">
                <span className="badge">{a.type}</span>
                <span className="status">{a.status}</span>
              </div>
              {a.reason && <p className="reason">{a.reason}</p>}
              <EvidenceList label="根拠 (Evidence)" items={a.evidence} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
