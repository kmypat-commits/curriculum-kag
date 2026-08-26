import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: 1,
  use: {
    baseURL: 'http://127.0.0.1:3001',
    channel: 'chrome',
    ...devices['Desktop Chrome'],
    trace: 'retain-on-failure',
  },
  reporter: [['list'], ['json', { outputFile: './test-results/e2e.json' }]],
});
