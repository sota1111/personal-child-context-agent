// Human-facing Japanese labels for enum values (SOT-2805).
//
// Deliberately non-clinical wording: this UI surfaces evidence and flags things to
// *confirm with a human*, it never asserts a medical decision or that something is
// "safe". In particular `no_relevant_match_found` is shown as "該当なし" with an explicit
// note that it is NOT a safety assertion (mirrors the backend contract in
// pcca.models.conflict).

import type { ContextStatus, ConflictClassification } from './types'

export const CONTEXT_STATUS_LABELS: Record<ContextStatus, string> = {
  known_present: '確認済み・該当あり (known_present)',
  explicitly_absent: '確認済み・該当なし (explicitly_absent)',
  unknown: '不明 (unknown)',
}

export const CONTEXT_STATUS_ORDER: ContextStatus[] = ['known_present', 'explicitly_absent', 'unknown']

export interface ClassificationLabel {
  title: string
  note: string
  tone: 'attention' | 'missing' | 'clarify' | 'none'
}

// Keys are lower-case (flow `classification` value). Names are shown alongside so the
// mapping to the backend spec is legible.
export const CLASSIFICATION_LABELS: Record<string, ClassificationLabel> = {
  confirmed_relevance: {
    title: '関連あり（要確認）',
    note: '文書と登録情報から関連が見つかりました。内容を確認してください。',
    tone: 'attention',
  },
  information_missing: {
    title: '情報不足',
    note: 'リスクを判断するのに必要な情報が不明です。保護者の確認が必要です。',
    tone: 'missing',
  },
  clarification_required: {
    title: '要再確認',
    note: '登録情報が古い、または矛盾しています。人による確認が必要です。',
    tone: 'clarify',
  },
  no_relevant_match_found: {
    title: '該当なし',
    note: '現在の情報からは該当が見つかりませんでした。※これは安全の断定ではありません。',
    tone: 'none',
  },
}

export function classificationLabel(value: string | null | undefined): ClassificationLabel {
  if (value && value in CLASSIFICATION_LABELS) return CLASSIFICATION_LABELS[value]
  return {
    title: value ?? '不明',
    note: '',
    tone: 'none',
  }
}

// Only used for narrowing when we want the strong ConflictClassification type.
export function isKnownClassification(value: string | null | undefined): value is ConflictClassification {
  return !!value && value in CLASSIFICATION_LABELS
}
