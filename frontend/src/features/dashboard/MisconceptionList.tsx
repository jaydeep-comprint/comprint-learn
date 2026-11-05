import { ChevronDown, ChevronRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import type { MisconceptionStat } from "@/lib/types";

import { Empty } from "./DashCard";

/** Misconception spread (spec 010): expanding a row shows the chosen distractor's text only
 * (never the correct answer) and who chose it. */
export function MisconceptionList({
  rows,
  onAssign,
  openId = null,
}: {
  rows: MisconceptionStat[];
  onAssign?: (concept: string) => void;
  /** Expand (and scroll to) this row on mount, e.g. from a summary citation (spec 011). The
   * parent remounts the list (`key`) when it changes. */
  openId?: string | null;
}) {
  const [open, setOpen] = useState<string | null>(openId);
  const target = useRef<HTMLLIElement | null>(null);
  const present = openId !== null && rows.some((m) => m.id === openId);
  useEffect(() => {
    if (present) target.current?.scrollIntoView?.({ block: "center" });
  }, [present]);
  if (rows.length === 0) return <Empty>No misconceptions picked up yet.</Empty>;
  return (
    <ul className="divide-y">
      {rows.map((m) => {
        const expanded = open === m.id;
        return (
          <li key={m.id} ref={m.id === openId ? target : undefined} className="py-2">
            <div className="flex items-start gap-2">
              <button
                type="button"
                aria-expanded={expanded}
                onClick={() => setOpen(expanded ? null : m.id)}
                className="flex flex-1 items-start gap-2 text-left"
              >
                {expanded ? (
                  <ChevronDown className="mt-0.5 size-4 shrink-0" aria-hidden />
                ) : (
                  <ChevronRight className="mt-0.5 size-4 shrink-0" aria-hidden />
                )}
                <span>
                  <span className="font-medium">{m.title}</span>
                  {m.concept_title && (
                    <span className="text-muted-foreground"> · {m.concept_title}</span>
                  )}
                  <span className="block text-sm text-muted-foreground">
                    chosen in {Math.round((m.rate ?? 0) * 100)}% of answers ({m.students}{" "}
                    {m.students === 1 ? "student" : "students"})
                  </span>
                </span>
              </button>
              {onAssign && m.concept && (
                <Button variant="outline" size="sm" onClick={() => onAssign(m.concept!)}>
                  Assign
                </Button>
              )}
            </div>
            {expanded && (
              <ul className="mt-2 space-y-2 pl-6 text-sm">
                {m.items.map((item, i) => (
                  <li key={i} className="rounded-md bg-muted/50 p-2">
                    <p className="line-clamp-3">{item.prompt}</p>
                    {item.chosen_text && (
                      <p className="mt-1">
                        <span className="text-muted-foreground">Chose: </span>
                        {item.chosen_text}
                      </p>
                    )}
                    <p className="mt-1 text-muted-foreground">{item.student_names.join(", ")}</p>
                  </li>
                ))}
              </ul>
            )}
          </li>
        );
      })}
    </ul>
  );
}
