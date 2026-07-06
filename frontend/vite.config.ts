import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The dev proxy mirrors the two API roots nginx proxies in production, so
// the client can stay same-origin (baseUrl: "") in every environment.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/transcribe": "http://localhost:8000",
      "/transcript": "http://localhost:8000",
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
