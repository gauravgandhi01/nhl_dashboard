import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  timeout: 120000,
  expect: { timeout: 30000 },
  workers: 1,
  use: {
    baseURL: process.env.DASHBOARD_URL || "http://127.0.0.1:8001",
    headless: true,
    screenshot: "only-on-failure",
  },
});
