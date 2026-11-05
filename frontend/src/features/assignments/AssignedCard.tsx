import { CheckCircle2, Clock } from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { brushUpPath, lessonPath } from "@/features/learn/paths";
import { dayDate, shortDate } from "@/lib/dates";
import type { MyAssignment } from "@/lib/types";
import { cn } from "@/lib/utils";

import { useMyAssignments } from "./api";

const MAX_STEPS = 5;
const DONE = new Set(["done_on_time", "done_late", "done_early"]);

function Due({ a }: { a: MyAssignment }) {
  if (DONE.has(a.status)) {
    return (
      <span className="flex items-center gap-1 text-emerald-700">
        <CheckCircle2 className="size-4" aria-hidden />
        Done ✓ {a.done_at ? shortDate(a.done_at) : ""}
      </span>
    );
  }
  if (a.status === "overdue") {
    return <span className="text-destructive">Overdue since {shortDate(a.due_date)}</span>;
  }
  return <span className="text-muted-foreground">Due {dayDate(a.due_date)}</span>;
}

function Item({ a }: { a: MyAssignment }) {
  const done = DONE.has(a.status);
  const steps = a.path.slice(0, MAX_STEPS);
  const more = a.path.length - steps.length;
  const next = a.next;
  return (
    <li className="space-y-2 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-medium">
          {a.title}{" "}
          <span className="text-sm font-normal text-muted-foreground">· {a.class_name}</span>
        </p>
        <Due a={a} />
      </div>
      {a.note && <p className="text-sm">{a.note}</p>}
      {!done && (
        <>
          <p className="text-sm text-muted-foreground">
            {a.learned} of {a.total} {a.total === 1 ? "concept" : "concepts"}
          </p>
          {steps.length > 0 && (
            <ol className="flex flex-wrap items-center gap-1 text-sm" aria-label="Path">
              {steps.map((s, i) => (
                <li key={s.concept} className="flex items-center gap-1">
                  {i > 0 && <span aria-hidden>→</span>}
                  <span
                    className={cn(
                      "rounded-full border px-2 py-0.5",
                      s.target && "font-medium",
                      s.status === "locked" && "text-muted-foreground",
                    )}
                  >
                    {s.title}
                    {s.waiting && <Clock className="ml-1 inline size-3" aria-label="Waiting" />}
                  </span>
                </li>
              ))}
              {more > 0 && <li className="text-muted-foreground">+ {more} more</li>}
            </ol>
          )}
          {next ? (
            <Button asChild size="sm">
              <Link
                to={
                  next.brush_up_id
                    ? brushUpPath(next.brush_up_id)
                    : lessonPath(a.course, next.concept)
                }
              >
                {next.brush_up_id ? `Brush up first: ${next.title}` : `Continue: ${next.title}`}
              </Link>
            </Button>
          ) : (
            <p className="text-sm text-muted-foreground">
              Waiting: retry tomorrow, or learn something else.
            </p>
          )}
        </>
      )}
    </li>
  );
}

/** Spec 010 Focus Mode: what the teacher assigned, at the top of home. Hidden when there's
 * nothing (or it fails to load): it never blocks home. */
export function AssignedCard() {
  const mine = useMyAssignments();
  if (!mine.data || mine.data.length === 0) return null;
  return (
    <section aria-labelledby="assigned-title" className="rounded-xl border p-4">
      <h2 id="assigned-title" className="text-lg font-semibold">
        Assigned by your teacher
      </h2>
      <ul className="divide-y">
        {mine.data.map((a) => (
          <Item key={a.id} a={a} />
        ))}
      </ul>
    </section>
  );
}
