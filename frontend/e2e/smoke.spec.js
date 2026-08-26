import { test, expect } from '@playwright/test';

test('login page loads without a blank screen', async ({ page }) => {
  await page.goto('/login');
  await expect(page.locator('body')).not.toHaveText('');
  await expect(page).toHaveTitle(/Curriculum|KAG/i);
});

test('backend health is reachable', async ({ request }) => {
  const response = await request.get('http://127.0.0.1:8000/health');
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  expect(body.status).toBe('healthy');
  expect(body.database).toBe('postgresql');
});

test('protected project route does not render a blank screen', async ({ page }) => {
  await page.goto('/projects/13');
  await expect(page.locator('body')).not.toHaveText('');
  await expect(page.locator('body')).toContainText(/Войти|Login|Curriculum|KAG/i);
});

test('protected graph route does not render a blank screen', async ({ page }) => {
  await page.goto('/projects/13/graph');
  await expect(page.locator('body')).not.toHaveText('');
  await expect(page.locator('body')).toContainText(/Войти|Login|Curriculum|KAG/i);
});
