import type { ErrorEvent } from "@sentry/react";
import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";
import { scrubBreadcrumb, scrubEvent } from "@/lib/observability";

const NAME = "Asha Verma";

describe("scrubEvent", () => {
  it("drops cookies, headers, bodies, query strings, extra and user details", () => {
    const event = {
      request: {
        url: `https://app.example.org/students?q=${NAME}`,
        method: "GET",
        cookies: { sb: "secret" },
        headers: { Authorization: "Bearer secret" },
        data: { name: NAME },
        query_string: `q=${NAME}`,
      },
      extra: { name: NAME },
      user: { id: "u1", username: NAME, email: "a@b.c", ip_address: "1.2.3.4" },
      breadcrumbs: [
        { category: "console", message: NAME },
        { category: "ui.click", message: NAME },
        { category: "xhr", data: { url: "/x" } },
        {
          category: "fetch",
          data: { method: "POST", url: `/api/v1/x?name=${NAME}`, status_code: 500, body: NAME },
        },
        { category: "navigation", data: { from: `/a?n=${NAME}`, to: "/b" } },
      ],
    } as unknown as ErrorEvent;
    const out = scrubEvent(event, { originalException: new Error("x") })!;
    expect(out.request).toEqual({ method: "GET", url: "https://app.example.org/students" });
    expect(out.extra).toBeUndefined();
    expect(out.user).toEqual({ id: "u1" });
    expect(out.breadcrumbs).toEqual([
      { category: "fetch", data: { method: "POST", url: "/api/v1/x", status_code: 500 } },
      { category: "navigation", data: undefined },
    ]);
    expect(JSON.stringify(out)).not.toContain("Asha");
  });

  it("drops API errors below 500 and keeps 5xx", () => {
    const event = {} as ErrorEvent;
    expect(scrubEvent(event, { originalException: new ApiError(429, "/x") })).toBeNull();
    expect(scrubEvent(event, { originalException: new ApiError(404, "/x") })).toBeNull();
    expect(scrubEvent(event, { originalException: new ApiError(500, "/x") })).not.toBeNull();
  });
});

describe("scrubBreadcrumb", () => {
  it("keeps only method, path and status of fetches", () => {
    expect(
      scrubBreadcrumb({
        category: "fetch",
        data: { method: "GET", url: "/a?b=c", status_code: 200 },
      }),
    ).toEqual({ category: "fetch", data: { method: "GET", url: "/a", status_code: 200 } });
  });
});
