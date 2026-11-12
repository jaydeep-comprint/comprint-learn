import { describe, expect, it } from "vitest";

import { buildCsp, buildHeadersFile, originOf, sentryOrigin } from "./csp";

const ENV = {
  VITE_API_BASE_URL: "https://api.example.org/",
  VITE_SUPABASE_URL: "https://abcd.supabase.co",
  VITE_SENTRY_DSN: "https://public123@o42.ingest.de.sentry.io/7",
};

function directives(csp: string): Record<string, string[]> {
  return Object.fromEntries(
    csp.split("; ").map((d) => {
      const [name, ...values] = d.split(" ");
      return [name, values];
    }),
  );
}

describe("buildCsp (spec 015)", () => {
  it("allows exactly the spec's sources", () => {
    const d = directives(buildCsp(ENV));
    expect(d["default-src"]).toEqual(["'self'"]);
    expect(d["script-src"]).toEqual(["'self'", "https://cdn.jsdelivr.net", "'wasm-unsafe-eval'"]);
    expect(d["worker-src"]).toEqual(["'self'", "blob:"]);
    expect(d["style-src"]).toEqual(["'self'", "'unsafe-inline'"]);
    expect(d["img-src"]).toEqual(["'self'", "data:"]);
    expect(d["font-src"]).toEqual(["'self'", "data:"]);
    expect(d["connect-src"]).toEqual([
      "'self'",
      "https://api.example.org",
      "https://abcd.supabase.co",
      "https://o42.ingest.de.sentry.io",
      "https://cdn.jsdelivr.net",
    ]);
    expect(d["frame-src"]).toEqual(["'none'"]);
    expect(d["frame-ancestors"]).toEqual(["'none'"]);
    expect(d["base-uri"]).toEqual(["'self'"]);
    expect(d["form-action"]).toEqual(["'self'"]);
    expect(buildCsp(ENV)).not.toContain(" 'unsafe-eval'");
    expect(buildCsp(ENV)).not.toMatch(/script-src[^;]*unsafe-inline/);
  });

  it("leaves out unset or same-origin values and never leaks the DSN key", () => {
    const d = directives(buildCsp({ VITE_API_BASE_URL: "" }));
    expect(d["connect-src"]).toEqual(["'self'", "https://cdn.jsdelivr.net"]);
    expect(buildCsp(ENV)).not.toContain("public123");
  });

  it("parses origins", () => {
    expect(originOf("/api")).toBeNull();
    expect(originOf("https://x.org/a/b")).toBe("https://x.org");
    expect(sentryOrigin("not a dsn")).toBeNull();
  });
});

describe("buildHeadersFile", () => {
  it("has the app rule and keeps the content-assets rule", () => {
    const file = buildHeadersFile(ENV);
    expect(file).toContain("/*\n  Content-Security-Policy: default-src 'self';");
    expect(file).toContain(
      "/content-assets/*\n  Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'\n  X-Content-Type-Options: nosniff",
    );
    expect(file).toContain("  X-Frame-Options: DENY");
  });
});
