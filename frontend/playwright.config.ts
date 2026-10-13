import { defineConfig } from '@playwright/test';

const isWindows = process.platform === 'win32';
const python = process.env.E2E_PYTHON ?? (isWindows ? '.venv\\Scripts\\python.exe' : 'python');
const apiPort = 8011;
const webPort = 5175;
// Locally we drive the installed Microsoft Edge (no browser download); CI installs Chromium.
const channel = process.env.PW_CHANNEL ?? (isWindows ? 'msedge' : undefined);

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    channel,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      // A throwaway data directory so the test never touches your local workspace.
      command: `${python} -m uvicorn datasentinel.main:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: '../backend',
      url: `http://127.0.0.1:${apiPort}/api/v1/ready`,
      env: { DATASENTINEL_DATA_DIR: 'var-e2e', DATASENTINEL_ENVIRONMENT: 'test', DATASENTINEL_LOG_LEVEL: 'WARNING' },
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npx vite --host 127.0.0.1 --port ${webPort}`,
      url: `http://127.0.0.1:${webPort}`,
      env: { DATASENTINEL_API_PROXY: `http://127.0.0.1:${apiPort}` },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
