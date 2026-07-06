import { defineConfig } from "@playwright/test";

// Runs against the full docker-compose stack: `docker compose up -d`,
// then `npm run e2e`. No webServer block on purpose — the demo stack is
// the system under test.
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  use: {
    // 127.0.0.1 rather than localhost: the docker port map binds IPv4, and a
    // stray listener on [::1]:5173 would otherwise shadow the stack.
    baseURL: process.env.PW_BASE_URL ?? "http://127.0.0.1:5173",
  },
});
