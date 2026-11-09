import { Compass } from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import type { DiagnosticState, Subject } from "@/lib/types";

import { placementPath, useCurrentDiagnostics } from "./api";

const SUBJECTS: Record<Subject, string> = { maths: "Maths", physics: "Physics", python: "Python" };

function label(d: DiagnosticState, all: DiagnosticState[]): string {
  const subject = d.course ? SUBJECTS[d.course.subject] : d.class_name;
  const twin = all.some((o) => o.id !== d.id && o.course?.subject === d.course?.subject);
  return twin ? `${subject} (${d.class_name})` : subject;
}

/** Home: one card per open placement check (spec 012). Renders nothing otherwise. */
export function PlacementCard() {
  const query = useCurrentDiagnostics();
  const open = query.data ?? [];
  if (open.length === 0) return null;
  return (
    <>
      {open.map((d) => (
        <section
          key={d.id}
          aria-labelledby={`placement-${d.id}`}
          className="space-y-3 rounded-xl border border-primary/40 bg-primary/5 p-4 sm:p-5"
        >
          <div className="flex items-start gap-3">
            <Compass className="mt-0.5 size-6 shrink-0 text-primary" aria-hidden />
            <div className="space-y-1">
              <h2 id={`placement-${d.id}`} className="text-lg font-semibold">
                Placement check · {label(d, open)}
              </h2>
              <p>
                Your teacher wants to see what you already know so you can skip it. Up to{" "}
                {d.max_questions} questions, no timer, no XP. You can pause any time.
              </p>
            </div>
          </div>
          <Button asChild className="w-full sm:w-auto">
            <Link to={placementPath(d.id)}>
              {d.status === "active" ? `Continue (${d.answered} answered)` : "Start"}
            </Link>
          </Button>
        </section>
      ))}
    </>
  );
}
