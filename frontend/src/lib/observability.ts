/**
 * Error tracking (spec 015): Sentry, scrubbed. Off unless `VITE_SENTRY_DSN` is set at build.
 *
 * Nothing personal leaves the browser: no session replay, no tracing, no console or click-text
 * breadcrumbs, no request bodies, headers or cookies, no `extra`. The user is `{id}` with tags
 * `org_id` and `role` only.
 */
import * as Sentry from "@sentry/react";
import type { Breadcrumb, ErrorEvent, EventHint } from "@sentry/react";

import { ApiError } from "@/lib/api";

const DSN: string | undefined = import.meta.env.VITE_SENTRY_DSN || undefined;

let enabled = false;

/** Call once, before the first render. A no-op without a DSN. */
export function initObservability(dsn: string | undefined = DSN): boolean {
  if (!dsn || enabled) return enabled;
  Sentry.init({
    dsn,
    environment: import.meta.env.MODE,
    // Sentry v11's replacement for `sendDefaultPii: false`: collect no user info, cookies,
    // headers, bodies, query params or frame variables.
    dataCollection: {
      userInfo: false,
      cookies: false,
      httpHeaders: false,
      httpBodies: [],
      urlQueryParams: false,
      stackFrameVariables: false,
    },
    // No tracing, replay or feedback: only the default error integrations, minus breadcrumbs we
    // don't want (configured below).
    integrations: (defaults) => [
      ...defaults.filter((i) => i.name !== "Breadcrumbs"),
      // Console breadcrumbs are dropped in `scrubBreadcrumb`.
      Sentry.breadcrumbsIntegration({ dom: false, xhr: false, fetch: true }),
    ],
    tracesSampleRate: 0,
    ignoreErrors: [/AbortError/, /The user aborted a request/, /ResizeObserver loop/],
    beforeBreadcrumb: scrubBreadcrumb,
    beforeSend: scrubEvent,
  });
  enabled = true;
  return true;
}

function pathOnly(url: unknown): string | undefined {
  if (typeof url !== "string") return undefined;
  try {
    const u = new URL(url, "http://x");
    return url.startsWith("http") ? `${u.origin}${u.pathname}` : u.pathname;
  } catch {
    return undefined;
  }
}

/** Fetch breadcrumbs keep method, path and status; console, click and xhr ones are dropped. */
export function scrubBreadcrumb(crumb: Breadcrumb): Breadcrumb | null {
  if (crumb.category === "console" || crumb.category?.startsWith("ui.")) return null;
  if (crumb.category === "xhr") return null;
  if (crumb.category === "fetch") {
    const data = crumb.data ?? {};
    return {
      ...crumb,
      data: {
        method: data.method,
        url: pathOnly(data.url),
        status_code: data.status_code,
      },
    };
  }
  return { ...crumb, data: undefined };
}

/** API errors below 500 are answers (403, 404, 409, 429...), not faults: never reported. */
function isClientApiError(hint: EventHint | undefined): boolean {
  const error = hint?.originalException;
  return error instanceof ApiError && error.status < 500;
}

export function scrubEvent(event: ErrorEvent, hint?: EventHint): ErrorEvent | null {
  if (isClientApiError(hint)) return null;
  if (event.request) {
    const { method, url } = event.request;
    event.request = { method, url: pathOnly(url) };
  }
  delete event.extra;
  if (event.user) event.user = event.user.id ? { id: event.user.id } : {};
  if (event.breadcrumbs) {
    event.breadcrumbs = event.breadcrumbs
      .map(scrubBreadcrumb)
      .filter((c): c is Breadcrumb => c !== null);
  }
  return event;
}

/** Ids only; `null` on sign-out. */
export function setObservedUser(user: { id: string; orgId: string; role: string } | null): void {
  if (!enabled) return;
  if (user === null) {
    Sentry.setUser(null);
    Sentry.setTag("org_id", undefined);
    Sentry.setTag("role", undefined);
    return;
  }
  Sentry.setUser({ id: user.id });
  Sentry.setTag("org_id", user.orgId);
  Sentry.setTag("role", user.role);
}

/** Report a non-API error; returns the Sentry event id (undefined when Sentry is off). */
export function reportError(error: unknown): string | undefined {
  if (!enabled || (error instanceof ApiError && error.status < 500)) return undefined;
  return Sentry.captureException(error);
}

const reported = new Set<string>();

/**
 * Report a message once per page session under a fixed fingerprint (a lab that blocks jsDelivr
 * must not send one event per student per lesson). No user content in `message`.
 */
export function reportOnce(key: string, message: string): void {
  if (!enabled || reported.has(key)) return;
  reported.add(key);
  Sentry.captureMessage(message, { level: "error", fingerprint: [key] });
}

/** Tests only. */
export function _resetObservability(): void {
  enabled = false;
  reported.clear();
}
