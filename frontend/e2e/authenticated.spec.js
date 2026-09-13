import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

test('authenticated dashboard flow renders after cookie login', async ({ page }) => {
  let authenticated = false

  await page.route('**/api/auth/me', async route => {
    if (!authenticated) {
      await route.fulfill({ status: 401, contentType: 'application/json', body: '{"detail":"Not authenticated"}' })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: 1, email: 'admin@example.test', full_name: 'Test Administrator', role: 'admin' }),
    })
  })

  await page.route('**/api/auth/login', async route => {
    authenticated = true
    await route.fulfill({ status: 204, headers: { 'Set-Cookie': 'access_token=test; HttpOnly; Path=/' } })
  })

  await page.route('**/api/projects', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([{ id: 101, title: 'Test programme', domain1: 'ICT', domain2: '', status: 'draft' }]),
    })
  })
  await page.route('**/api/repository/stats', async route => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{"total_courses":42}' })
  })

  await page.goto('/login')
  await expect(page.locator('body')).toContainText(/Войти|Login/)
  await expect(page.getByLabel(/Войти|Login/)).toBeVisible()
  await expect(page.getByLabel(/Пароль|Password/)).toBeVisible()
  await page.getByLabel(/Войти|Login/).fill('admin@example.test')
  await page.getByLabel(/Пароль|Password/).fill('test-password')
  await page.getByRole('button', { name: /Войти|Login/ }).click()

  await expect(page).toHaveURL(/\/$/)
  await expect(page.locator('h1')).toContainText(/Проекты образовательных программ|Projects of educational programmes/i)
  await expect(page.getByText('Test programme')).toBeVisible()
  await expect(page.getByText('42')).toBeVisible()

  const accessibility = await new AxeBuilder({ page }).analyze()
  const blockingViolations = accessibility.violations.filter(({ impact }) => impact === 'critical' || impact === 'serious')
  expect(blockingViolations, JSON.stringify(blockingViolations, null, 2)).toEqual([])
})
