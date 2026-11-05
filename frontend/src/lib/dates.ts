/** "12 Nov" for an ISO date ("2026-11-12") or datetime, in Indian English. */
export function shortDate(iso: string): string {
  const date = iso.length === 10 ? new Date(`${iso}T00:00:00`) : new Date(iso);
  return date.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}
