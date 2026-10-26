import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:8000",
    viewport: { width: 390, height: 844 },
    reducedMotion: "reduce",
  },
  workers: 1,
  reporter: "list",
});
