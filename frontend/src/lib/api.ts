const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "";

/** An HTTP response from the API with a non-2xx status (the API was reachable). */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, path: string) {
    super(`GET ${path} failed with HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
  }
}

/** GET a JSON resource from the API. Throws `ApiError` on non-2xx, or the fetch error if unreachable. */
export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new ApiError(response.status, path);
  }
  return (await response.json()) as T;
}
