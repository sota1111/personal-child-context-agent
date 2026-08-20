// Thin API client for the FastAPI backend. Every call is same-origin (`/api/**`):
// in dev Vite proxies it to the local backend; in production nginx reverse-proxies it
// to the backend Cloud Run service, so the session cookie stays first-party.
// `credentials: 'include'` sends the HMAC session cookie the backend issued.
import type {
  ChildContextItem,
  ChildContextInput,
  FlowResult,
  TrackedAction,
} from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    // Surface the backend's `detail` when present, else a generic status message.
    const data = (await res.json().catch(() => ({}))) as { detail?: string }
    throw new ApiError(res.status, data.detail ?? `Request failed (${res.status})`)
  }
  // 204/empty bodies parse as {} so callers needn't special-case them.
  return (await res.json().catch(() => ({}))) as T
}

// --- auth ---------------------------------------------------------------------

export async function login(email: string, password: string): Promise<void> {
  await request('/auth/session', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}

export async function logout(): Promise<void> {
  await request('/auth/logout', { method: 'POST' })
}

export async function fetchMe(): Promise<{ owner_id: string }> {
  return request('/auth/me')
}

// --- child context ------------------------------------------------------------

export async function getChildContext(childId: string): Promise<ChildContextItem[]> {
  const data = await request<{ contexts: ChildContextItem[] }>(
    `/children/${encodeURIComponent(childId)}/context`,
  )
  return data.contexts ?? []
}

export async function putChildContext(
  childId: string,
  contexts: ChildContextInput[],
): Promise<ChildContextItem[]> {
  const data = await request<{ contexts: ChildContextItem[] }>(
    `/children/${encodeURIComponent(childId)}/context`,
    { method: 'PUT', body: JSON.stringify({ contexts }) },
  )
  return data.contexts ?? []
}

export async function getChildActions(childId: string): Promise<TrackedAction[]> {
  const data = await request<{ actions: TrackedAction[] }>(
    `/children/${encodeURIComponent(childId)}/actions`,
  )
  return data.actions ?? []
}

// --- flow ---------------------------------------------------------------------

export interface ProcessDocumentArgs {
  child_id: string
  document_id: string
  document_ref: string
  source?: string
  // Idempotency keys of planned actions the parent approved. Anything omitted is
  // tracked but never executed (the human-approval gate lives in the backend).
  approvals?: string[]
}

export async function processDocument(args: ProcessDocumentArgs): Promise<FlowResult> {
  return request('/documents:process', {
    method: 'POST',
    body: JSON.stringify(args),
  })
}

export async function reevaluateActions(
  childId: string,
): Promise<{ child_id: string; reevaluated: TrackedAction[] }> {
  return request('/actions:reevaluate', {
    method: 'POST',
    body: JSON.stringify({ child_id: childId }),
  })
}
