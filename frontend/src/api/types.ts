// Response/request types mirroring `pcca.api.serialization` exactly (SOT-2805).
// Evidence and the three-way context status are preserved verbatim; the frontend adds
// no medical/safety judgement of its own.

export type ContextStatus = 'known_present' | 'explicitly_absent' | 'unknown'

// A stored Personal Context fact, as returned by the backend.
export interface ChildContextItem {
  child_id: string
  context_type: string
  status: ContextStatus
  value: string | null
  source: string | null
  notes: string | null
  last_confirmed_at: string | null
  updated_at: string | null
}

// One fact sent to `PUT /api/children/{child_id}/context`.
export interface ChildContextInput {
  context_type: string
  status: ContextStatus
  value?: string | null
  source?: string | null
  notes?: string | null
  // Days since the parent last confirmed the fact (drives freshness checks).
  // null ⇒ never confirmed (treated as stale by the Conflict Tool).
  confirmed_days_ago?: number | null
}

export interface TrackedAction {
  action_id: string
  child_id: string
  type: string
  status: string
  reason: string | null
  evidence: string[]
  due_at: string | null
  idempotency_key: string | null
  external_resource_id: string | null
  resolution: string | null
  source_document_id: string | null
  finding_rule: string | null
  created_at: string | null
  updated_at: string | null
}

export interface PlannedAction {
  key: string
  tool: string
  action_type: string
  waiting_status: string
  reason: string | null
  payload: Record<string, unknown>
  evidence: string[]
  finding_rule: string | null
  due_at: string | null
}

// The Conflict-Tool classification, surfaced through the flow's `classification` field.
export type ConflictClassification =
  | 'confirmed_relevance'
  | 'information_missing'
  | 'clarification_required'
  | 'no_relevant_match_found'

export interface FlowResult {
  child_id: string
  document_id: string
  detect: Record<string, unknown> | null
  classification: string | null
  findings: Array<Record<string, unknown>>
  planned: PlannedAction[]
  actions: TrackedAction[]
  reevaluated: TrackedAction[]
}
