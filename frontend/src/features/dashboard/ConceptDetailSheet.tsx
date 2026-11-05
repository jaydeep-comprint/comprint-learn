import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import type { DashboardWindow } from "@/lib/types";

import { useConceptDetail } from "./api";
import { pct } from "./format";
import { MisconceptionList } from "./MisconceptionList";

const KIND_LABELS: Record<string, string> = {
  misconception_check: "Learn check",
  kp_question: "KP question",
  practice: "Practice",
};

/** Concept detail (spec 010): per KP and per item numbers, misconceptions, and who is where. */
export function ConceptDetailSheet({
  classId,
  concept,
  window,
  onClose,
  onAssign,
}: {
  classId: string;
  concept: string | null;
  window: DashboardWindow;
  onClose: () => void;
  onAssign: (concept: string) => void;
}) {
  const detail = useConceptDetail(classId, concept, window);
  const d = detail.data;
  return (
    <Sheet open={concept !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto p-4 sm:max-w-xl">
        <SheetTitle className="pr-8">{d?.title ?? "Concept"}</SheetTitle>
        <SheetDescription className="sr-only">
          How the class is doing on this concept
        </SheetDescription>
        {detail.isPending ? (
          <Skeleton className="h-64" />
        ) : detail.isError || !d ? (
          <div role="alert" className="text-sm">
            Couldn&apos;t load this.{" "}
            <Button variant="outline" size="sm" onClick={() => void detail.refetch()}>
              Try again
            </Button>
          </div>
        ) : (
          <div className="space-y-6 text-sm">
            <Button onClick={() => onAssign(d.concept)}>Assign this concept</Button>
            <section className="space-y-2">
              <h3 className="font-medium">Students now</h3>
              {d.students.stuck.length > 0 && (
                <div>
                  <p className="text-muted-foreground">Stuck</p>
                  <ul>
                    {d.students.stuck.map((s) => (
                      <li key={s.student_id}>
                        <Link
                          to={`/classes/${classId}/students/${s.student_id}`}
                          className="hover:underline"
                        >
                          {s.display_name}
                        </Link>{" "}
                        <span className="text-muted-foreground">· {s.reason}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <p>
                In progress: {d.students.in_progress.map((s) => s.display_name).join(", ") || "—"}
              </p>
              <p>Learned: {d.students.learned.map((s) => s.display_name).join(", ") || "—"}</p>
              <p className="text-muted-foreground">
                Ready {d.students.ready} · Locked {d.students.locked}
              </p>
            </section>
            <section className="space-y-2">
              <h3 className="font-medium">Knowledge points</h3>
              <ul className="space-y-1">
                {d.kps.map((kp) => (
                  <li key={kp.title} className="flex justify-between gap-2">
                    <span>{kp.title}</span>
                    <span className="tabular-nums text-muted-foreground">
                      {kp.tries} tries · {pct(kp.fail_rate)} failed · {kp.hints} hints
                    </span>
                  </li>
                ))}
              </ul>
            </section>
            <section className="space-y-2">
              <h3 className="font-medium">Questions</h3>
              <ul className="space-y-2">
                {d.items.map((item, i) => (
                  <li key={i} className="rounded-md border p-2">
                    <p className="line-clamp-3">{item.prompt}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {KIND_LABELS[item.kind] ?? item.kind} · {item.answers} answers
                      {item.correct_pct !== null && ` · ${item.correct_pct}% correct`}
                      {item.avg_seconds !== null && ` · ${Math.round(item.avg_seconds)} s avg`}
                    </p>
                  </li>
                ))}
              </ul>
            </section>
            <section className="space-y-2">
              <h3 className="font-medium">Misconceptions</h3>
              <MisconceptionList rows={d.misconceptions} />
            </section>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
