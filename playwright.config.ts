import { defineConfig, devices } from "@playwright/test";

// One flow, chromium only: this suite proves the happy path works end to end (sign in, read a
// part, answer a full round, see it pass), not cross-browser compatibility.
//
// Two web servers: the FastAPI backend on the fake stack against the local Postgres *test*
// database (scripts/e2e-backend.sh seeds one published subject before serving), and the
// Next.js dev server the frontend already uses. `reuseExistingServer` outside CI so a server
// already running locally (e.g. `npm run dev` in another terminal) is left alone.
const PORT = 3000;
const BASE_URL = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "dot" : "list",

  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  webServer: [
    {
      command: "bash scripts/e2e-backend.sh",
      url: "http://localhost:8000/api/health",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: "npm run dev",
      url: BASE_URL,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});
