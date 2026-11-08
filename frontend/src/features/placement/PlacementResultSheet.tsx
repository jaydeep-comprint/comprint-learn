import { Skeleton } from "@/components/ui/skeleton";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { shortDate } from "@/lib/dates";
import type { PlacementOutcome } from "@/lib/types";

import { useStudentOutcomes } from "./api";

const GROUPS: { outcome: PlacementOutcome; title: string }[] = [
  { outcome: "learned", title: "Placed" },
  { outcome: "conditional", title: "Placed · check soon" },
  { outcome: "demoted", title: "Back to learn" },
  { outcome: "unchanged", title: "Unchanged" },
];

/** The latest finished placement check of one student, concepts grouped by outcome. */
export function PlacementResultSheet({
  classId,
  studentId,
  onClose,
}: {
  classId: string;
  studentId: string | null;
  onClose: () => void;
}) {
  const query = useStudentOutcomes(classId, studentId);
  const data = query.data;
  return (
    <Sheet open={studentId !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto p-4 sm:max-w-lg">
        <SheetTitle className="pr-8">{data?.display_name ?? "Placement result"}</SheetTitle>
        <SheetDescription>
          {data?.finished_at
            ? `Placement check finished ${shortDate(data.finished_at)}`
            : "Placement check"}
        </SheetDescription>
        {query.isPending ? (
          <Skeleton className="mt-4 h-40" />
        ) : query.isError || !data ? (
          <p className="mt-4 text-sm text-destructive">Couldn&apos;t load the result.</p>
        ) : data.concepts.length === 0 ? (
          <p className="mt-4 text-sm text-muted-foreground">No finished placement check yet.</p>
        ) : (
          <div className="mt-4 space-y-5">
            {GROUPS.map(({ outcome, title }) => {
              const concepts = data.concepts.filter((c) => c.outcome === outcome);
              if (concepts.length === 0) return null;
              return (
                <section key={outcome} aria-label={title} className="space-y-1">
                  <h3 className="text-sm font-semibold">
                    {title} <span className="text-muted-foreground">({concepts.length})</span>
                  </h3>
                  <ul className="divide-y text-sm">
                    {concepts.map((c) => (
                      <li key={c.concept.id} className="py-1.5">
                        {c.concept.title}
                      </li>
                    ))}
                  </ul>
                </section>
              );
            })}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
