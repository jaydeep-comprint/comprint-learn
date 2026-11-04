import { CheckCircle2, Circle, CircleDashed, Lock } from "lucide-react";

import type { LessonStatus } from "@/lib/types";
import { STATUS_LABELS } from "@/features/learn/paths";
import { cn } from "@/lib/utils";

const ICONS = {
  finished: { Icon: CheckCircle2, className: "text-[var(--success)]" },
  in_progress: { Icon: CircleDashed, className: "text-primary" },
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
