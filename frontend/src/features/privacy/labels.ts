import type { AuditAction, AuditEvent } from "@/lib/types";

export const AUDIT_LABELS: Record<AuditAction, string> = {
  consent_recorded: "Consent recorded",
  consent_withdrawn: "Consent withdrawn",
  export_downloaded: "Data downloaded",
  erase_requested: "Erasure requested",
  erase_cancelled: "Erasure cancelled",
  erase_completed: "Student erased",
  password_reset: "Password reset",
  user_deactivated: "Deactivated",
  user_reactivated: "Reactivated",
};

/** The Details column: the event's counts and versions in words. */
export function auditDetails(e: AuditEvent): string {
  const m = e.meta;
  const parts: string[] = [];
  if (typeof m.form === "string") parts.push(`form ${m.form}`);
  if (typeof m.messages_purged === "number")
    parts.push(`${m.messages_purged} chat messages deleted`);
  if (m.source === "cli") parts.push("from the command line");
  if (typeof m.due_at === "string") parts.push(`due ${m.due_at.slice(0, 10)}`);
  if (m.was_active === false) parts.push("was already deactivated");
  if (m.role === "teacher") parts.push("teacher");
  return parts.join(" · ");
}
