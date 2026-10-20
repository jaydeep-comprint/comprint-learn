import { getAccessToken, signOut } from "@/lib/supabase";

const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "";

/** An HTTP response from the API with a non-2xx status (the API was reachable). */
export class ApiError extends Error {
  readonly status: number;
  /** Machine-readable code from the API body (`unauthenticated`, `not_found`, ...), if any. */
  readonly code: string | undefined;

  constructor(status: number, path: string, code?: string, message?: string) {
    super(message ?? `${path} failed with HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
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
    throw new ApiError(response.status, path);
  }
  return (await response.json()) as T;
}

type FetchOptions = { method?: string; body?: unknown; signal?: AbortSignal };

async function errorFromResponse(response: Response, path: string): Promise<ApiError> {
  let code: string | undefined;
  let message: string | undefined;
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object") {
      const b = body as { code?: unknown; message?: unknown; detail?: unknown };
      if (typeof b.code === "string") code = b.code;
      if (typeof b.message === "string") message = b.message;
      // FastAPI validation errors: {detail: [{msg}]}
      if (!message && Array.isArray(b.detail) && b.detail[0]?.msg) {
        message = String(b.detail[0].msg).replace(/^Value error, /, "");
      }
    }
  } catch {
    // Not JSON: keep the generic message.
  }
  return new ApiError(response.status, path, code, message);
}

/**
 * Call the API with the signed-in user's bearer token.
 *
 * 401 → sign out and go to /login. 403 `password_change_required` → go to /change-password.
 */
export async function apiFetch<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const token = await getAccessToken();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
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
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
