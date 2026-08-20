import { useCallback, useEffect, useState } from 'react'
import { useChildId } from '../hooks/useChildId'
import ChildIdBar from '../components/ChildIdBar'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { TrackedAction } from '../api/types'
import EvidenceList from '../components/EvidenceList'

// Lists a child's tracked actions (each with its reason & evidence) and lets the parent
// re-evaluate still-open actions against newly-registered context.
export default function ActionsPage() {
  const [childId, setChildId] = useChildId()
  const [actions, setActions] = useState<TrackedAction[]>([])
  const [loading, setLoading] = useState(true)
  const [reevaluating, setReevaluating] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (id: string) => {
    setLoading(true)
    setError(null)
    try {
      setActions(await api.getChildActions(id))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '読み込みに失敗しました')
      setActions([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(childId)
  }, [childId, load])

  const reevaluate = async () => {
    setReevaluating(true)
    setError(null)
    setNote(null)
    try {
      const res = await api.reevaluateActions(childId)
      setNote(`再評価: ${res.reevaluated.length} 件が更新されました。`)
      await load(childId)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '再評価に失敗しました')
    } finally {
      setReevaluating(false)
    }
  }

  return (
    <section className="page">
      <h2>Actions 一覧</h2>
      <ChildIdBar childId={childId} onChange={setChildId} />
      <div className="actions-bar">
        <button type="button" className="secondary" onClick={() => load(childId)} disabled={loading}>
          再読み込み
        </button>
        <button type="button" className="primary" onClick={reevaluate} disabled={reevaluating}>
          {reevaluating ? '再評価中…' : '未処理を再評価'}
        </button>
      </div>
      {note && <p className="ok" role="status">{note}</p>}

      {loading ? (
        <p className="loading">読み込み中…</p>
      ) : actions.length === 0 ? (
        <p className="muted">トラッキング中の action はありません。</p>
      ) : (
        <ul className="actions-list">
          {actions.map((a) => (
            <li key={a.action_id} className="action card">
              <div className="action-head">
                <span className="badge">{a.type}</span>
                <span className="status">{a.status}</span>
                {a.due_at && <span className="due">期限: {a.due_at}</span>}
              </div>
              {a.reason && <p className="reason">{a.reason}</p>}
              <EvidenceList label="根拠 (Evidence)" items={a.evidence} />
              {a.resolution && <p className="resolution">結果: {a.resolution}</p>}
            </li>
          ))}
        </ul>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}
