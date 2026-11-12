/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv } from "vite";

import { contentAssets } from "./vite/content-assets";
import { spaHeaders, spaHeadersFile } from "./vite/csp";

export default defineConfig(({ mode }) => {
  // Spec 015: the CSP's origins come from the build env (one policy for dist/_headers and preview).
  const env = loadEnv(mode, process.cwd(), "VITE_");
  return {
    plugins: [
      react(),
      tailwindcss(),
      contentAssets(fileURLToPath(new URL("../content", import.meta.url))),
      spaHeadersFile(env),
    ],
    resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
    server: {
      port: 5173,
      // Same-origin API calls in dev, so the backend needs no CORS locally.
      proxy: { "/api": "http://localhost:8000" },
    },
    // `pnpm build && pnpm preview` runs the built app under the deployed CSP. (preview.headers
    // can't do per-path rules, so the content-assets rule isn't reproduced here.)
    preview: {
      headers: spaHeaders(env),
      proxy: { "/api": "http://localhost:8000" },
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      include: ["src/**/*.test.{ts,tsx}", "vite/**/*.test.ts"],
    },
  };
});
