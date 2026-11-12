// Spec 015: the SPA's Content-Security-Policy, one source for both the deployed `_headers` file
// (Cloudflare Pages / Netlify format, emitted into dist/ at build) and `vite preview`.
//
// Origins come from the build env: VITE_API_BASE_URL (when the API is on another origin),
// VITE_SUPABASE_URL and VITE_SENTRY_DSN. Pyodide is a dynamic import() inside a same-origin module
// worker, loading its script, wasm and packages from jsDelivr.
import type { Plugin } from "vite";

import { PYODIDE_URL } from "../src/features/code/pyodideVersion";
import { URL_PREFIX } from "./content-assets";

/** Only the pinned Pyodide folder, not all of jsDelivr (which serves any npm package: with an
 * HTML injection, a whole-host source would be a CSP bypass). Spec 015 security review. */
export const PYODIDE_SOURCE = PYODIDE_URL;

export type CspEnv = {
  VITE_API_BASE_URL?: string;
  VITE_SUPABASE_URL?: string;
  VITE_SENTRY_DSN?: string;
};

/** The origin of a URL, or null when it's empty, relative or invalid. */
export function originOf(url: string | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.origin : null;
  } catch {
    return null;
  }
}

/** A DSN is `https://<key>@<host>/<project>`: the browser posts events to `https://<host>`. */
export function sentryOrigin(dsn: string | undefined): string | null {
  if (!dsn) return null;
  try {
    const u = new URL(dsn);
    return `${u.protocol}//${u.host}`;
  } catch {
    return null;
  }
}

export function buildCsp(env: CspEnv): string {
  const connect = [
    "'self'",
    originOf(env.VITE_API_BASE_URL),
    originOf(env.VITE_SUPABASE_URL),
    sentryOrigin(env.VITE_SENTRY_DSN),
    PYODIDE_SOURCE,
  ].filter((v, i, all): v is string => v !== null && all.indexOf(v) === i);
  const directives: [string, string[]][] = [
    ["default-src", ["'self'"]],
    // Pyodide: its script from jsDelivr, and WebAssembly compilation.
    ["script-src", ["'self'", PYODIDE_SOURCE, "'wasm-unsafe-eval'"]],
    ["worker-src", ["'self'", "blob:"]],
    // KaTeX, React Flow, Mermaid's SVG <style> and sonner set inline styles.
    ["style-src", ["'self'", "'unsafe-inline'"]],
    ["img-src", ["'self'", "data:"]],
    ["font-src", ["'self'", "data:"]], // KaTeX
    ["connect-src", connect],
    ["object-src", ["'none'"]],
    ["frame-src", ["'none'"]], // YouTube is links only, no iframes
    ["frame-ancestors", ["'none'"]],
    ["base-uri", ["'self'"]],
    ["form-action", ["'self'"]],
  ];
  return directives.map(([name, values]) => `${name} ${values.join(" ")}`).join("; ");
}

/** Headers for every SPA response (the API sets its own). */
export function spaHeaders(env: CspEnv): Record<string, string> {
  return {
    "Content-Security-Policy": buildCsp(env),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    // The SPA host's own HSTS may be off on a custom domain (spec 015 review, area 9).
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
  };
}

/** Content images keep their own stricter rule (an SVG can't run script or load anything). */
export const CONTENT_ASSET_HEADERS: Record<string, string> = {
  "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
  "X-Content-Type-Options": "nosniff",
};

function rule(path: string, headers: Record<string, string>): string {
  return [path, ...Object.entries(headers).map(([k, v]) => `  ${k}: ${v}`)].join("\n");
}

/** The `_headers` file (Cloudflare Pages / Netlify). The Vercel equivalent is in the runbook. */
export function buildHeadersFile(env: CspEnv): string {
  return `${[rule("/*", spaHeaders(env)), rule(`${URL_PREFIX}*`, CONTENT_ASSET_HEADERS)].join("\n\n")}\n`;
}

/** Emits dist/_headers at build. */
export function spaHeadersFile(env: CspEnv): Plugin {
  return {
    name: "spa-headers-file",
    apply: "build",
    generateBundle() {
      this.emitFile({ type: "asset", fileName: "_headers", source: buildHeadersFile(env) });
    },
  };
}
