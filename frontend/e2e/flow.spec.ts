import { test, expect } from '@playwright/test'
import { installApiMocks, login } from './support/mockApi'

test('未認証で / にアクセスすると /login にリダイレクトされる', async ({ page }) => {
  await installApiMocks(page, { authed: false })
  await page.goto('/')
  await expect(page).toHaveURL(/\/login/)
  await expect(page.locator('input[type="email"]')).toBeVisible()
  await expect(page.locator('input[type="password"]')).toBeVisible()
})

test('有効なセッションがあれば保護ページに直接アクセスできる', async ({ page }) => {
  await installApiMocks(page, { authed: true })
  await page.goto('/context')
  await expect(page).not.toHaveURL(/\/login/)
  await expect(page.getByRole('heading', { name: 'Child Context 編集' })).toBeVisible()
})

test('ログイン→文書投入→Conflict/Action/Evidence 表示→承認', async ({ page }) => {
  await installApiMocks(page, { authed: false })

  // ログイン
  await login(page)
  await expect(page.getByRole('heading', { name: 'Child Context 編集' })).toBeVisible()

  // 文書投入ページへ
  await page.getByRole('link', { name: '文書投入' }).click()
  await expect(page).toHaveURL(/\/ingest/)

  // 学校文書を処理
  await page.locator('textarea').fill('12:00 に与薬予定があります。')
  await page.getByRole('button', { name: '文書を処理する' }).click()

  // Conflict 判定と Evidence が表示される
  await expect(page.getByText('判定: 関連あり（要確認）')).toBeVisible()
  await expect(page.getByText('学校文書の根拠')).toBeVisible()
  // Evidence (verbatim school-document text) is rendered in the finding.
  await expect(page.locator('.finding .evidence').getByText('12:00 に与薬予定')).toBeVisible()
  await expect(page.getByText('登録文脈の根拠')).toBeVisible()

  // Action が表示される
  await expect(page.getByText('waiting_for_parent').first()).toBeVisible()

  // 承認して実行
  await page.locator('.planned .planned-check input[type="checkbox"]').check()
  await page.getByRole('button', { name: '承認して実行' }).click()

  // 承認後は action が completed になる
  await expect(page.getByText('completed').first()).toBeVisible()
})

test('安全断定をしない文言（該当なしは安全ではない旨）がフッターに表示される', async ({ page }) => {
  await installApiMocks(page, { authed: true })
  await page.goto('/context')
  await expect(page.getByText(/医療判断や安全の断定は行いません/)).toBeVisible()
})
