import { defineConfig, devices } from '@playwright/test'

const python = process.platform === 'win32' ? '..\\.venv\\Scripts\\python.exe' : '../.venv/bin/python'

export default defineConfig({
  testDir: './tests', fullyParallel: false, workers: 1, timeout: 30_000,
  use: { baseURL: 'http://127.0.0.1:5174', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    { command: `${python} -m uvicorn api.main:app --app-dir .. --host 127.0.0.1 --port 8765`, url: 'http://127.0.0.1:8765/health', env: { PUMPRADAR_MOCK: '1', PUMPRADAR_DB: ':memory:' }, reuseExistingServer: false },
    { command: 'npm run dev -- --host 127.0.0.1 --port 5174 --strictPort', url: 'http://127.0.0.1:5174', env: { PUMPRADAR_API_TARGET: 'http://127.0.0.1:8765', VITE_API_URL: '/api' }, reuseExistingServer: false },
  ],
})
