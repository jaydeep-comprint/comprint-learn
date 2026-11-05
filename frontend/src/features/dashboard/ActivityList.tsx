import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { shortDate } from "@/lib/dates";
import type { ActivityRow } from "@/lib/types";

import { useActivity } from "./api";
import { Empty } from "./DashCard";

const KIND: Record<ActivityRow["kind"], string> = {
  kp: "KP try",
  remediation: "Brush-up",
  practice: "Practice",
  review: "Review",
  quiz: "Quiz",
};

function duration(seconds: number): string {
  if (seconds < 60) return `${seconds} s`;
  return `${Math.round(seconds / 60)} min`;
}

/** The student's last ended sessions on the class course, newest first, with "Load more". */
export function ActivityList({ classId, studentId }: { classId: string; studentId: string }) {
  const activity = useActivity(classId, studentId);
  if (activity.isPending) return <Skeleton className="h-32" />;
  if (activity.isError) {
    return (
      <div role="alert" className="text-sm">
        Couldn&apos;t load activity.{" "}
        <Button variant="outline" size="sm" onClick={() => void activity.refetch()}>
          Try again
        </Button>
      </div>
    );
  }
  const rows = activity.data.pages.flat();
  if (rows.length === 0) return <Empty>No activity yet.</Empty>;
  return (
    <div className="space-y-2">
      <ul className="divide-y text-sm">
        {rows.map((r, i) => (
          <li
            key={`${r.ended_at}-${i}`}
            className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2"
          >
            <span className="w-20 shrink-0 text-muted-foreground">{KIND[r.kind]}</span>
            <span className="min-w-0 flex-1 truncate font-medium">{r.title}</span>
            <span className={r.outcome === "passed" ? "text-emerald-700" : "text-destructive"}>
              {r.outcome === "passed" ? "Passed" : "Failed"}
            </span>
            <span className="tabular-nums text-muted-foreground">
              {r.xp === null ? "—" : `${r.xp} XP`} · {r.answered} answered · {r.hints} hints ·{" "}
              {duration(r.seconds)} · {shortDate(r.ended_at)}
            </span>
          </li>
        ))}
      </ul>
      {activity.hasNextPage && (
        <Button
          variant="outline"
          size="sm"
          onClick={() => void activity.fetchNextPage()}
          disabled={activity.isFetchingNextPage}
        >
          {activity.isFetchingNextPage ? "Loading…" : "Load more"}
        </Button>
      )}
    </div>
  );
}
