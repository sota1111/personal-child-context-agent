import { useCallback, useState } from 'react'

const STORAGE_KEY = 'pcca.childId'
const DEFAULT_CHILD_ID = 'demo-child'

// The active child id is shared across the Context / Ingest / Actions pages via
// localStorage, so switching child on one page carries over to the others. There is no
// child-list endpoint on the backend yet (context/actions are keyed by an arbitrary
// child id), so the parent simply types/keeps the id they use.
export function useChildId(): [string, (id: string) => void] {
  const [childId, setChildIdState] = useState<string>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) || DEFAULT_CHILD_ID
    } catch {
      return DEFAULT_CHILD_ID
    }
  })

  const setChildId = useCallback((id: string) => {
    const next = id.trim() || DEFAULT_CHILD_ID
    setChildIdState(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // ignore storage failures (private mode etc.)
    }
  }, [])

  return [childId, setChildId]
}
