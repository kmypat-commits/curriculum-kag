import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

test('real backend cookie login and CSRF-protected session work', async ({ page, context }) => {
  await page.goto('/login')
  await page.getByLabel(/Войти|Login/).fill('browser-smoke@example.test')
  await page.getByLabel(/Пароль|Password/).fill('browser-smoke-password')
  await page.getByRole('button', { name: /Войти|Login/ }).click()

  await expect(page).toHaveURL(/\/$/)
  await expect(page.locator('h1')).toContainText(/Проекты образовательных программ|Projects of educational programmes/i)
  await expect(page.locator('body')).not.toContainText(/Could not validate credentials|Traceback|500 Internal Server Error/i)

  const cookies = await context.cookies()
  const access = cookies.find(cookie => cookie.name === 'access_token')
  const csrf = cookies.find(cookie => cookie.name === 'csrf_token')
  expect(access?.httpOnly).toBeTruthy()
  expect(csrf?.httpOnly).toBeFalsy()
  expect(csrf?.sameSite).toBe('Lax')

  const accessibility = await new AxeBuilder({ page }).analyze()
  const blockingViolations = accessibility.violations.filter(({ impact }) => impact === 'critical' || impact === 'serious')
  expect(blockingViolations, JSON.stringify(blockingViolations, null, 2)).toEqual([])
})
