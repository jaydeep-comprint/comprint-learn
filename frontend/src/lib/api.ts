import { getAccessToken, signOut } from "@/lib/supabase";

const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "";

/** An HTTP response from the API with a non-2xx status (the API was reachable). */
export class ApiError extends Error {
  readonly status: number;
  /** Machine-readable code from the API body (`unauthenticated`, `not_found`, ...), if any. */
  readonly code: string | undefined;
  /** The parsed JSON body, if any (e.g. `prereqs` on `concept_locked`). */
  readonly body: unknown;
  /** Spec 015: the request id (body `request_id`, else the `X-Request-ID` header). */
  readonly requestId: string | undefined;

  constructor(
    status: number,
    path: string,
    code?: string,
    message?: string,
    body?: unknown,
    requestId?: string,
  ) {
    super(message ?? `${path} failed with HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.body = body;
    this.requestId = requestId;
  }
}

/** The global query `retry` (spec 015): 4xx (403, 404, 409, 429...) are answers, not glitches. */
export function retryUnlessClientError(count: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return count < 2;
}

/** Full-page redirects (also clear in-memory state such as the query cache). Tests replace `go`. */
export const redirect = {
  go(path: string): void {
    window.location.assign(path);
  },
};

/** GET a JSON resource without auth (the health check). Throws `ApiError` on non-2xx. */
export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new ApiError(
      response.status,
      path,
      undefined,
      undefined,
      undefined,
      response.headers.get("X-Request-ID") ?? undefined,
    );
  }
  return (await response.json()) as T;
}

type FetchOptions = {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
  /** Let the request outlive the page (pagehide / tab hidden). */
  keepalive?: boolean;
};

async function errorFromResponse(response: Response, path: string): Promise<ApiError> {
  let code: string | undefined;
  let message: string | undefined;
  let body: unknown;
  let requestId = response.headers.get("X-Request-ID") ?? undefined;
  try {
    body = await response.json();
    if (body && typeof body === "object") {
      const b = body as {
        code?: unknown;
        message?: unknown;
        detail?: unknown;
        request_id?: unknown;
      };
      if (typeof b.code === "string") code = b.code;
      if (typeof b.message === "string") message = b.message;
      if (typeof b.request_id === "string") requestId = b.request_id;
      // FastAPI validation errors: {detail: [{msg}]}
      if (!message && Array.isArray(b.detail) && b.detail[0]?.msg) {
        message = String(b.detail[0].msg).replace(/^Value error, /, "");
      }
    }
  } catch {
    // Not JSON: keep the generic message.
  }
  return new ApiError(response.status, path, code, message, body, requestId);
}

/** A signed-in request; non-2xx → `ApiError` (401 signs out, a temp password redirects). */
async function authedFetch(path: string, options: FetchOptions = {}): Promise<Response> {
  const token = await getAccessToken();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
    keepalive: options.keepalive,
  });

  if (!response.ok) {
    const error = await errorFromResponse(response, path);
    if (response.status === 401) {
      await signOut();
      redirect.go("/login");
    } else if (error.code === "password_change_required") {
      redirect.go("/change-password");
    }
    throw error;
  }
  return response;
}

/**
 * Call the API with the signed-in user's bearer token.
 *
 * 401 → sign out and go to /login. 403 `password_change_required` → go to /change-password.
 */
export async function apiFetch<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const response = await authedFetch(path, options);
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

/** The filename from `Content-Disposition: attachment; filename="..."`, if any. */
export function attachmentName(header: string | null): string | null {
  const match = header?.match(/filename="([^"]+)"/);
  return match?.[1] ?? null;
}

/** Spec 014: download an authenticated attachment (the student export) as a file. */
export async function apiDownload(path: string, fallbackName: string): Promise<void> {
  const response = await authedFetch(path);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = attachmentName(response.headers.get("Content-Disposition")) ?? fallbackName;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
