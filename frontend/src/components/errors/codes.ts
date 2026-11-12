import { ApiError } from "@/lib/api";

/** First 8 characters: short enough to read out to a teacher. */
export function shortCode(id: string | undefined | null): string | null {
  return id ? id.replace(/-/g, "").slice(0, 8) : null;
}

/** The code shown for an error: the API's request id, else the Sentry event id. */
export function errorCode(error: unknown, eventId: string | undefined): string | null {
  if (error instanceof ApiError && error.requestId) return error.requestId;
  return eventId ?? null;
}
