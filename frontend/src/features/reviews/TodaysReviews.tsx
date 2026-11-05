import { AlertCircle, ChevronRight, Repeat } from "lucide-react";
import { Link } from "react-router";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { reviewPath, useReviewQueue } from "@/features/reviews/api";
import { shortDate } from "@/lib/dates";
import { type ReviewQueue, SUBJECT_LABELS } from "@/lib/types";

function emptyText(q: ReviewQueue): string {
  if (q.done_today > 0 || q.more_due > 0) return "That's today's reviews done 🎉";
  if (q.next_due_on) return `No reviews due. Next one on ${shortDate(q.next_due_on)}.`;
  return "No reviews due.";
}

/** Home: the reviews offered today (spec 007). Hidden until the student has a card. */
export function TodaysReviews() {
  const query = useReviewQueue();
  if (query.isPending) {
    return <Skeleton className="h-24 w-full rounded-xl" aria-busy="true" />;
  }
  if (query.isError) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-xl border p-6 text-center">
        <AlertCircle className="size-6 text-muted-foreground" aria-hidden />
        <p>Couldn&apos;t load your reviews.</p>
        <Button variant="outline" onClick={() => query.refetch()}>
          Try again
        </Button>
      </div>
    );
  }
  const q = query.data;
  if (!q.has_cards) return null;
  return (
    <section aria-labelledby="todays-reviews" className="space-y-3 rounded-xl border p-4 sm:p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 id="todays-reviews" className="text-lg font-semibold">
          Today&apos;s reviews
        </h2>
        <span className="text-sm text-muted-foreground tabular-nums">
          {Math.min(q.done_today, q.cap)} of {q.cap} done today
        </span>
      </div>
      {q.offered.length === 0 ? (
        <p className="text-muted-foreground">{emptyText(q)}</p>
      ) : (
        <ul className="space-y-1">
          {q.offered.map((o) => (
            <li key={o.concept.id}>
              <Link
                to={reviewPath(o.concept.id)}
                className="flex min-h-11 items-center gap-3 rounded-md px-2 py-2 hover:bg-muted"
              >
                <Repeat className="size-5 shrink-0 text-primary" aria-hidden />
                <span className="min-w-0 flex-1">
                  {o.concept.title}
                  <span className="text-muted-foreground"> · {SUBJECT_LABELS[o.subject]}</span>
                </span>
                {o.reason === "quiz_miss" && <Badge variant="secondary">From your quiz</Badge>}
                {o.active && <span className="text-sm text-muted-foreground">Continue</span>}
                <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
