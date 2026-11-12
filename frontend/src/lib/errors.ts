import { shortCode } from "@/components/errors/codes";
import { ApiError } from "@/lib/api";

export const RATE_LIMITED_MESSAGE = "Too many requests. Wait a moment and try again.";
export const TOO_LARGE_MESSAGE = "That's too large to send.";

/**
 * A message fit for a toast: the API's own message when it sent one. Spec 015: 5xx get
 * "(code xxxxxxxx)" so a student can tell their teacher; 429 and 413 have fixed texts.
 */
export function errorMessage(
  error: unknown,
  fallback = "Something went wrong. Try again.",
): string {
  if (!(error instanceof ApiError)) return fallback;
  if (error.status === 429) return RATE_LIMITED_MESSAGE;
  if (error.status === 413) return TOO_LARGE_MESSAGE;
  if (error.status >= 500) {
    const base = error.code && error.message ? error.message : fallback;
    const code = shortCode(error.requestId);
    return code ? `${base} (code ${code})` : base;
  }
  if (error.code && error.message) return error.message;
  if (error.status === 422 && error.message) return error.message;
  return fallback;
}
