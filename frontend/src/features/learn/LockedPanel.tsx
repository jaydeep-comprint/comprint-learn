import { ChevronRight } from "lucide-react";
import { Link } from "react-router";

import { lessonPath, STATUS_LABELS } from "@/features/learn/paths";
import { StatusIcon } from "@/features/learn/StatusIcon";
import type { LockedPrereq } from "@/lib/types";

/** "Finish these first": the unfinished direct prerequisites of a locked concept. */
export function LockedPanel({ course, prereqs }: { course: string; prereqs: LockedPrereq[] }) {
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        This lesson builds on these. Finish them first and it opens.
      </p>
      <ul className="divide-y rounded-lg border">
        {prereqs.map((p) => {
          const open = p.status === "ready" || p.status === "in_progress";
          const body = (
            <>
              <StatusIcon status={p.status} />
              <span className="min-w-0 flex-1">
                <span className="block font-medium">{p.title}</span>
                <span className="block text-sm text-muted-foreground">
                  {STATUS_LABELS[p.status]}
                </span>
              </span>
              {open && <ChevronRight className="size-4 text-muted-foreground" aria-hidden />}
            </>
          );
          return (
            <li key={p.id}>
              {open ? (
                <Link
                  to={lessonPath(course, p.id)}
                  className="flex min-h-11 items-center gap-3 p-3 hover:bg-muted"
                >
                  {body}
                </Link>
              ) : (
                <div className="flex min-h-11 items-center gap-3 p-3">{body}</div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
