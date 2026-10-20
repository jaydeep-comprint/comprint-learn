/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

import { contentAssets } from "./vite/content-assets";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    contentAssets(fileURLToPath(new URL("../content", import.meta.url))),
  ],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    // Same-origin API calls in dev, so the backend needs no CORS locally.
    proxy: { "/api": "http://localhost:8000" },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "vite/**/*.test.ts"],
  },
});
