/** "12 Nov" for an ISO date ("2026-11-12") or datetime, in Indian English. */
export function shortDate(iso: string): string {
  const date = iso.length === 10 ? new Date(`${iso}T00:00:00`) : new Date(iso);
  return date.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

/** Today's date in IST as "YYYY-MM-DD" (due dates and the dashboard's days are IST). */
export function todayIst(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(now);
}

/** "YYYY-MM-DD" plus `days`. */
export function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** "Fri 8 Nov" for an ISO date. */
export function dayDate(iso: string): string {
  const date = new Date(`${iso.slice(0, 10)}T00:00:00`);
  return date.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
}
