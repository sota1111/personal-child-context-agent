import { expect, type Page } from '@playwright/test'

// Deterministic mock for every `/api/**` call — the backend is never started (mirrors the
// おたよりナビ e2e harness). `authed` controls whether /auth/me returns a session.
export interface MockOptions {
  authed?: boolean
}

// A FlowResult with one confirmed-relevance finding (with both sides of Evidence), one
// planned action, and one tracked action — enough to exercise Conflict + Action + Evidence
// display and the approval path.
function flowResult(childId: string, approvals: string[]) {
  const executed = approvals.includes('plan-med-1')
  return {
    child_id: childId,
    document_id: 'doc-1',
    detect: { has_content: true },
    classification: 'confirmed_relevance',
    findings: [
      {
        classification: 'CONFIRMED_RELEVANCE',
        rule: 'medication_schedule_match',
        reason: '学校の与薬予定と登録済みの服薬情報が一致しました。保護者の確認が必要です。',
        school_evidence: ['12:00 に与薬予定'],
        personal_context_evidence: ['scheduled_medication: 12:00 (known_present)'],
      },
    ],
    planned: [
      {
        key: 'plan-med-1',
        tool: 'action_tools',
        action_type: 'medication_confirmation',
        waiting_status: 'waiting_for_parent',
        reason: '与薬の実施可否を保護者に確認します。',
        payload: { time: '12:00' },
        evidence: ['12:00 に与薬予定'],
        finding_rule: 'medication_schedule_match',
        due_at: null,
      },
    ],
    actions: [
      {
        action_id: 'act-1',
        child_id: childId,
        type: 'medication_confirmation',
        status: executed ? 'completed' : 'waiting_for_parent',
        reason: '与薬の実施可否を保護者に確認します。',
        evidence: ['12:00 に与薬予定'],
        due_at: null,
        idempotency_key: 'plan-med-1',
        external_resource_id: executed ? 'evt-123' : null,
        resolution: executed ? 'confirmed' : null,
        source_document_id: 'doc-1',
        finding_rule: 'medication_schedule_match',
        created_at: '2026-06-01T00:00:00Z',
        updated_at: '2026-06-01T00:00:00Z',
      },
    ],
    reevaluated: [],
  }
}

export async function installApiMocks(page: Page, opts: MockOptions = {}) {
  const authed = opts.authed ?? false
  await page.route('**/api/**', async (route) => {
    const req = route.request()
    const url = new URL(req.url())
    const path = url.pathname
    const method = req.method()
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })

    if (path.endsWith('/auth/me')) {
      return authed
        ? json({ status: 'authenticated', owner_id: 'owner-abc' })
        : json({ detail: 'Not authenticated' }, 401)
    }
    if (path.endsWith('/auth/session')) return json({ success: true, email: 'test@example.com' })
    if (path.endsWith('/auth/logout')) return json({ success: true })

    if (path.includes('/context')) {
      const childId = decodeURIComponent(path.split('/children/')[1]?.split('/')[0] ?? 'demo-child')
      if (method === 'PUT') {
        const body = (req.postDataJSON() ?? {}) as { contexts?: unknown[] }
        return json({ child_id: childId, contexts: body.contexts ?? [] })
      }
      return json({ child_id: childId, contexts: [] })
    }
    if (path.includes('/actions') && path.includes('/children/')) {
      const childId = decodeURIComponent(path.split('/children/')[1]?.split('/')[0] ?? 'demo-child')
      return json({ child_id: childId, actions: [] })
    }
    if (path.endsWith('/documents:process')) {
      const body = (req.postDataJSON() ?? {}) as { child_id?: string; approvals?: string[] }
      return json(flowResult(body.child_id ?? 'demo-child', body.approvals ?? []))
    }
    if (path.endsWith('/actions:reevaluate')) {
      const body = (req.postDataJSON() ?? {}) as { child_id?: string }
      return json({ child_id: body.child_id ?? 'demo-child', reevaluated: [] })
    }
    return json({}, 200)
  })
}

// Sign in through the real login form and land on /context.
export async function login(page: Page) {
  await page.goto('/login')
  await page.locator('input[type="email"]').fill('test@example.com')
  await page.locator('input[type="password"]').fill('password123')
  await page.locator('button[type="submit"]').click()
  await expect(page).toHaveURL(/\/context/)
}
