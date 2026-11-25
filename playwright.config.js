// Bateria de testes de interface do Mensura.
// Usa o Google Chrome já instalado na máquina (channel: 'chrome'), sem baixar navegadores.
const { defineConfig, devices } = require('@playwright/test');

const PY = process.platform === 'win32' ? '.venv\\Scripts\\python.exe' : '.venv/bin/python';

module.exports = defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  fullyParallel: true,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:8000',
    channel: 'chrome',
    headless: true,
    serviceWorkers: 'block',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], channel: 'chrome' } },
    { name: 'mobile', use: { viewport: { width: 375, height: 760 }, isMobile: true, hasTouch: true, channel: 'chrome' } },
  ],
  webServer: {
    command: `${PY} -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`,
    url: 'http://127.0.0.1:8000/api/status',
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
