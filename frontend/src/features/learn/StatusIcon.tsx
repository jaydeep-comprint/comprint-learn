import { CheckCircle2, Circle, Lock } from "lucide-react";

import type { LessonStatus } from "@/lib/types";
import { STATUS_LABELS } from "@/features/learn/paths";
import { cn } from "@/lib/utils";

/** A ring half filled: "in progress" (lucide has no half-ring). */
function HalfRing({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden>
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="2" />
      <path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor" />
    </svg>
  );
}

const ICONS = {
  learned: { Icon: CheckCircle2, className: "text-[var(--success)]" },
  in_progress: { Icon: HalfRing, className: "text-[var(--warning)]" },
  ready: { Icon: Circle, className: "text-primary" },
  locked: { Icon: Lock, className: "text-muted-foreground" },
} as const;

export function StatusIcon({ status, className }: { status: LessonStatus; className?: string }) {
  const { Icon, className: tone } = ICONS[status];
  return (
    <span className={cn("inline-flex shrink-0", className)}>
      <Icon className={cn("size-5", tone)} aria-hidden />
      <span className="sr-only">{STATUS_LABELS[status]}</span>
    </span>
  );
}
