import { useCallback, useEffect, useState } from 'react'
import { useChildId } from '../hooks/useChildId'
import ChildIdBar from '../components/ChildIdBar'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { ChildContextInput } from '../api/types'
import { CONTEXT_STATUS_LABELS, CONTEXT_STATUS_ORDER } from '../api/labels'

// Editable rows for the parent-managed Personal Context. The three-way status
// (known_present / explicitly_absent / unknown) is preserved exactly — `unknown` is
// never silently turned into an absence (that safety invariant lives in the backend,
// and the UI simply never collapses the choices).
interface Row {
  context_type: string
  status: ChildContextInput['status']
  value: string
  source: string
  notes: string
  confirmed_days_ago: string // kept as text; '' ⇒ never confirmed (null)
}

function emptyRow(): Row {
  return { context_type: '', status: 'unknown', value: '', source: '', notes: '', confirmed_days_ago: '' }
}

export default function ContextPage() {
  const [childId, setChildId] = useChildId()
  const [rows, setRows] = useState<Row[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const load = useCallback(async (id: string) => {
    setLoading(true)
    setError(null)
    setSaved(false)
    try {
      const contexts = await api.getChildContext(id)
      setRows(
        contexts.map((c) => ({
          context_type: c.context_type,
          status: c.status,
          value: c.value ?? '',
          source: c.source ?? '',
          notes: c.notes ?? '',
          confirmed_days_ago: '',
        })),
      )
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '読み込みに失敗しました')
      setRows([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(childId)
  }, [childId, load])

  const updateRow = (i: number, patch: Partial<Row>) => {
    setRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))
    setSaved(false)
  }

  const removeRow = (i: number) => {
    setRows((prev) => prev.filter((_, idx) => idx !== i))
    setSaved(false)
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      const payload: ChildContextInput[] = rows
        .filter((r) => r.context_type.trim())
        .map((r) => ({
          context_type: r.context_type.trim(),
          status: r.status,
          value: r.value.trim() || null,
          source: r.source.trim() || null,
          notes: r.notes.trim() || null,
          confirmed_days_ago:
            r.confirmed_days_ago.trim() === '' ? null : Number(r.confirmed_days_ago),
        }))
      await api.putChildContext(childId, payload)
      setSaved(true)
      await load(childId)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存に失敗しました')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="page">
      <h2>Child Context 編集</h2>
      <ChildIdBar childId={childId} onChange={setChildId} />
      <p className="muted">
        保護者が把握している事実を登録します。状態は「該当あり / 該当なし / 不明」の3値で、
        「不明」は「該当なし（安全）」とは区別されます。
      </p>

      {loading ? (
        <p className="loading">読み込み中…</p>
      ) : (
        <>
          {rows.length === 0 && <p className="muted">登録された文脈はまだありません。</p>}
          <div className="rows">
            {rows.map((row, i) => (
              <div className="context-row card" key={i}>
                <label className="field">
                  <span>種別 (context_type)</span>
                  <input
                    type="text"
                    value={row.context_type}
                    placeholder="food_allergy / scheduled_medication ..."
                    onChange={(e) => updateRow(i, { context_type: e.target.value })}
                  />
                </label>
                <label className="field">
                  <span>状態</span>
                  <select
                    value={row.status}
                    onChange={(e) => updateRow(i, { status: e.target.value as Row['status'] })}
                  >
                    {CONTEXT_STATUS_ORDER.map((s) => (
                      <option key={s} value={s}>
                        {CONTEXT_STATUS_LABELS[s]}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>値 (value)</span>
                  <input
                    type="text"
                    value={row.value}
                    placeholder="peanut / 12:00 ..."
                    onChange={(e) => updateRow(i, { value: e.target.value })}
                  />
                </label>
                <label className="field">
                  <span>出所 (source)</span>
                  <input
                    type="text"
                    value={row.source}
                    onChange={(e) => updateRow(i, { source: e.target.value })}
                  />
                </label>
                <label className="field">
                  <span>最終確認からの日数</span>
                  <input
                    type="number"
                    min={0}
                    value={row.confirmed_days_ago}
                    placeholder="空欄=未確認"
                    onChange={(e) => updateRow(i, { confirmed_days_ago: e.target.value })}
                  />
                </label>
                <label className="field field-wide">
                  <span>メモ (notes)</span>
                  <input
                    type="text"
                    value={row.notes}
                    onChange={(e) => updateRow(i, { notes: e.target.value })}
                  />
                </label>
                <button type="button" className="link-button danger" onClick={() => removeRow(i)}>
                  削除
                </button>
              </div>
            ))}
          </div>

          <div className="actions-bar">
            <button
              type="button"
              className="secondary"
              onClick={() => setRows((prev) => [...prev, emptyRow()])}
            >
              ＋ 行を追加
            </button>
            <button type="button" className="primary" onClick={save} disabled={saving}>
              {saving ? '保存中…' : '保存'}
            </button>
          </div>
          {saved && <p className="ok" role="status">保存しました。</p>}
        </>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}
