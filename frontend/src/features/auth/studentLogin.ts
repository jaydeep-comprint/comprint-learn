/** Helpers for student sign-in: synthetic auth email and the remembered school code. */

const SCHOOL_CODE_KEY = "schoolCode";

export function normalizeSchoolCode(code: string): string {
  return code.replace(/\s+/g, "").toUpperCase();
}

/** Must match `student_auth_email` in backend/app/services/tenancy.py. */
export function studentAuthEmail(schoolCode: string, username: string): string {
  const code = normalizeSchoolCode(schoolCode).toLowerCase();
  return `${username.trim().toLowerCase()}@${code}.students.invalid`;
}

// The school code isn't personal data, so it stays on shared lab computers after sign-out.
export function rememberedSchoolCode(): string {
  try {
    return localStorage.getItem(SCHOOL_CODE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function rememberSchoolCode(code: string): void {
  try {
    localStorage.setItem(SCHOOL_CODE_KEY, normalizeSchoolCode(code));
  } catch {
    // Storage blocked (private mode): nothing to remember.
  }
}
