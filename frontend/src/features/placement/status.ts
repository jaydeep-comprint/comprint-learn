import { shortDate } from "@/lib/dates";
import type { PlacementStudentRow } from "@/lib/types";

export function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

export function statusText(row: PlacementStudentRow): string {
  switch (row.status) {
    case "not_sent":
      return "Not sent";
    case "sent":
      return "Sent";
    case "active":
      return `In progress (${row.answered} answered)`;
    case "finished":
      return row.finished_at ? `Finished ${shortDate(row.finished_at)}` : "Finished";
    case "cancelled":
      return "Cancelled";
  }
}

export function countsText(row: PlacementStudentRow): string | null {
  if (!row.counts) return null;
  const c = row.counts;
  return `learned ${c.learned} · conditional ${c.conditional} · demoted ${c.demoted}`;
}

export function sentMessage(sent: number, skipped: number): string {
  const who = `Sent to ${sent} student${sent === 1 ? "" : "s"}`;
  return skipped ? `${who} (${skipped} already had one)` : who;
}
