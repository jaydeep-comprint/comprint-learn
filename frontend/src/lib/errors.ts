import { ApiError } from "@/lib/api";

/** A message fit for a toast: the API's own message when it sent one. */
export function errorMessage(
  error: unknown,
  fallback = "Something went wrong. Try again.",
): string {
  if (error instanceof ApiError && error.code && error.message) return error.message;
  if (error instanceof ApiError && error.status === 422 && error.message) return error.message;
  return fallback;
}
