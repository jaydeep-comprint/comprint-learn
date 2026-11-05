import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { dayDate, shortDate } from "@/lib/dates";

import { useAssignment } from "./api";
import { ASSIGNMENT_STATUS } from "./status";

/** One assignment's per-student statuses and next concept (spec 010). */
export function AssignmentDetailSheet({
  classId,
  id,
  onClose,
}: {
  classId: string;
  id: string | null;
  onClose: () => void;
}) {
  const detail = useAssignment(classId, id);
  const d = detail.data;
  return (
    <Sheet open={id !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto p-4 sm:max-w-lg">
        <SheetTitle className="pr-8">{d?.title ?? "Assignment"}</SheetTitle>
        <SheetDescription>{d ? `Due ${dayDate(d.due_date)}` : " "}</SheetDescription>
        {detail.isPending ? (
          <Skeleton className="h-40" />
        ) : detail.isError || !d ? (
          <p className="text-sm text-destructive">Couldn&apos;t load this assignment.</p>
        ) : !d.content_available ? (
          <p className="text-sm text-muted-foreground">Content no longer available.</p>
        ) : d.students.length === 0 ? (
          <p className="text-sm text-muted-foreground">No students.</p>
        ) : (
          <ul className="divide-y text-sm">
            {d.students.map((s) => (
              <li key={s.student_id} className="flex flex-wrap justify-between gap-2 py-2">
                <span className="font-medium">{s.display_name}</span>
                <span className="text-muted-foreground">
                  {s.status === "in_progress"
                    ? `${s.learned} of ${s.total}`
                    : ASSIGNMENT_STATUS[s.status]}
                  {s.done_at && s.status !== "done_early" && ` · ${shortDate(s.done_at)}`}
                  {s.next && ` · next: ${s.next.title}`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </SheetContent>
    </Sheet>
  );
}
