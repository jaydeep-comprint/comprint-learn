export const MAX_NEW_STUDENTS = 60;
export const MAX_NAME_LENGTH = 40;

/** One name per line; blank lines ignored; duplicates kept (they become different students). */
export function parseNames(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

export function namesError(names: string[]): string | null {
  if (names.length > MAX_NEW_STUDENTS) {
    return `That's ${names.length} names. Add at most ${MAX_NEW_STUDENTS} at a time.`;
  }
  const long = names.findIndex((n) => n.length > MAX_NAME_LENGTH);
  if (long >= 0) return `Name ${long + 1} is longer than ${MAX_NAME_LENGTH} characters.`;
  return null;
}
