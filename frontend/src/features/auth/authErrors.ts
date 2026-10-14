import { isAuthApiError, isAuthRetryableFetchError } from "@supabase/supabase-js";

export const STUDENT_BAD_CREDENTIALS = "Incorrect school code, username or password.";
export const STAFF_BAD_CREDENTIALS = "Incorrect email or password.";
export const AUTH_UNREACHABLE = "Can't reach the sign-in service. Try again in a minute.";
export const LINK_EXPIRED = "This link has expired. Ask your school admin to resend the invite.";

/** One message for every credential problem (no hints about which part was wrong). */
export function signInErrorMessage(error: unknown, badCredentials: string): string {
  if (isAuthRetryableFetchError(error)) return AUTH_UNREACHABLE;
  if (isAuthApiError(error) && error.status >= 500) return AUTH_UNREACHABLE;
  if (error instanceof TypeError) return AUTH_UNREACHABLE; // fetch failed
  return badCredentials;
}
