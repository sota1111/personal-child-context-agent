import { useState } from 'react'
import { useChildId } from '../hooks/useChildId'
import ChildIdBar from '../components/ChildIdBar'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { FlowResult } from '../api/types'
import FlowResultView from '../components/FlowResultView'
import EvidenceList from '../components/EvidenceList'

// Submit a school document to the flow and show the FlowResult. Planned actions are
// listed with an approval checkbox; approving re-submits the same document with the
// selected idempotency keys (the human-approval gate: an action is only executed when
// its key is in `approvals`).
export default function IngestPage() {
  const [childId, setChildId] = useChildId()
  const [documentId, setDocumentId] = useState('doc-1')
  const [source, setSource] = useState('handout')
  const [text, setText] = useState('')
  const [result, setResult] = useState<FlowResult | null>(null)
  const [approvedKeys, setApprovedKeys] = useState<Record<string, boolean>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const process = async (approvals: string[]) => {
    setBusy(true)
    setError(null)
    try {
      const res = await api.processDocument({
        child_id: childId,
        document_id: documentId.trim() || 'doc-1',
        document_ref: text,
        source: source.trim() || 'unknown',
        approvals,
      })
      setResult(res)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '処理に失敗しました')
    } finally {
      setBusy(false)
    }
  }

  const onSubmit = async () => {
    setApprovedKeys({})
    await process([])
  }

  const onApprove = async () => {
    const keys = Object.entries(approvedKeys)
      .filter(([, v]) => v)
      .map(([k]) => k)
    await process(keys)
  }

  const planned = result?.planned ?? []
  const anyApproved = Object.values(approvedKeys).some(Boolean)

  return (
    <section className="page">
      <h2>文書投入 → FlowResult</h2>
      <ChildIdBar childId={childId} onChange={setChildId} />

      <div className="ingest-form">
        <label className="field">
          <span>document_id</span>
          <input type="text" value={documentId} onChange={(e) => setDocumentId(e.target.value)} />
        </label>
        <label className="field">
          <span>source</span>
          <input type="text" value={source} onChange={(e) => setSource(e.target.value)} />
        </label>
        <label className="field field-wide">
          <span>学校文書の本文</span>
          <textarea
            rows={6}
            value={text}
            placeholder="学校からのおたより本文を貼り付けてください"
            onChange={(e) => setText(e.target.value)}
          />
        </label>
        <button type="button" className="primary" onClick={onSubmit} disabled={busy || !text.trim()}>
          {busy ? '処理中…' : '文書を処理する'}
        </button>
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {result && (
        <>
          {planned.length > 0 && (
            <div className="planned card">
              <h4>承認待ちの Planned Actions</h4>
              <p className="muted">
                チェックした action のみ、承認して実行します（未承認はトラッキングのみ・未実行）。
              </p>
              <ul className="planned-list">
                {planned.map((p) => (
                  <li key={p.key} className="planned-item">
                    <label className="planned-check">
                      <input
                        type="checkbox"
                        checked={!!approvedKeys[p.key]}
                        onChange={(e) =>
                          setApprovedKeys((prev) => ({ ...prev, [p.key]: e.target.checked }))
                        }
                      />
                      <span className="badge">{p.action_type}</span>
                      <span className="status">{p.waiting_status}</span>
                    </label>
                    {p.reason && <p className="reason">{p.reason}</p>}
                    <EvidenceList label="根拠 (Evidence)" items={p.evidence} />
                  </li>
                ))}
              </ul>
              <button type="button" className="primary" onClick={onApprove} disabled={busy || !anyApproved}>
                {busy ? '実行中…' : '承認して実行'}
              </button>
            </div>
          )}
          <FlowResultView result={result} />
        </>
      )}
    </section>
  )
}
