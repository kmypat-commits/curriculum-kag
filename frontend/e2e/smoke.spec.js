import { test, expect } from '@playwright/test';

test('login page loads without a blank screen', async ({ page }) => {
  await page.goto('/login');
  await expect(page.locator('body')).not.toHaveText('');
  await expect(page).toHaveTitle(/Curriculum|KAG/i);
});
