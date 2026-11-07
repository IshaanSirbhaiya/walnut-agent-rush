import { defineConfig } from '@playwright/test';

// Pure logic specs: no browser, no server, no port (the main config starts the app on 3101).
//   npx playwright test -c tests/e2e/pure.config.ts
export default defineConfig({
  testDir: '.',
  testMatch: /answer-text\.spec\.ts$/,
  workers: 1,
  reporter: [['list']],
});
