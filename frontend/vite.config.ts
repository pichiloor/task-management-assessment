import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development the Vite server forwards /api to the compose stack's nginx
// (same origin, as in production). Override with VITE_API_PROXY.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": process.env.VITE_API_PROXY ?? "http://localhost:8080",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
