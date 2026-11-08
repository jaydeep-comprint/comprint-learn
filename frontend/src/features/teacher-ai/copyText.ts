import type { TeacherSummary } from "@/lib/types";

import { resourceLabel } from "./links";

/** Plain text for Copy: claims and notes with names filled in, no citation numbers. */
export function copyText(s: TeacherSummary): string {
  const lines = ["AI summary", ...s.claims.map((c) => `- ${c.text}`)];
  if (s.notes.length > 0) {
    lines.push("", s.kind === "student" ? "Suggestion" : "Re-teaching notes");
    s.notes.forEach((n, i) => {
      lines.push(`${i + 1}. ${n.focus}`, `   Why: ${n.why.text}`);
      if (n.revisit.length > 0) {
        lines.push(`   Revisit: ${n.revisit.map(resourceLabel).join("; ")}`);
      }
      if (n.group.length > 0) {
        lines.push(`   Group: ${n.group.map((g) => g.display_name).join(", ")}`);
      }
    });
  }
  return lines.join("\n");
}

/** "just now", "5 min ago", "2 h ago", "3 days ago". */
export function timeAgo(iso: string, now: Date = new Date()): string {
  const minutes = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "1 day ago" : `${days} days ago`;
}
