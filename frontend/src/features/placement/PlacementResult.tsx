import { CheckCircle2 } from "lucide-react";
import { Link, useParams } from "react-router";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import type { ConceptRef } from "@/lib/types";
import { NotFoundPage } from "@/pages/NotFoundPage";

import { useDiagnostic, useDiagnosticResult } from "./api";

function List({ title, hint, concepts }: { title: string; hint: string; concepts: ConceptRef[] }) {
  return (
    <section aria-label={title} className="space-y-2 rounded-lg border p-4">
      <h2 className="font-semibold">
        {title} <span className="text-muted-foreground">({concepts.length})</span>
      </h2>
      <p className="text-sm text-muted-foreground">{hint}</p>
      {concepts.length > 0 ? (
        <ul className="list-disc space-y-1 pl-5">
          {concepts.map((c) => (
            <li key={c.id}>{c.title}</li>
          ))}
        </ul>
      ) : (
        <p className="text-sm">None</p>
      )}
    </section>
  );
}

/** `/placement/:id/result`: what the student placed out of (spec 012). No per-question marks. */
export function PlacementResult() {
  const { id = "" } = useParams();
  const state = useDiagnostic(id);
  const result = useDiagnosticResult(id);
  if (state.error instanceof ApiError && [403, 404].includes(state.error.status)) {
    return <NotFoundPage />;
  }
  const placed = (result.data?.learned.length ?? 0) + (result.data?.conditional.length ?? 0);
  const course = state.data?.course;
  return (
    <main className="mx-auto min-h-svh max-w-prose space-y-5 px-4 py-6 pb-10">
      {result.isPending ? (
        <Skeleton className="h-48" />
      ) : result.isError ? (
        <div className="space-y-3 py-8 text-center">
          <p>Couldn&apos;t load your result.</p>
          <Button variant="outline" onClick={() => void result.refetch()}>
            Try again
          </Button>
        </div>
      ) : state.data?.empty ? (
        <div className="space-y-4 py-8 text-center">
          <p>Nothing to check right now. You can carry on learning as usual.</p>
          <Button asChild variant="outline">
            <Link to="/">Back home</Link>
          </Button>
        </div>
      ) : (
        <>
          <div className="space-y-1">
            <CheckCircle2 className="size-10 text-[var(--success)]" aria-hidden />
            <h1 className="text-2xl font-semibold tracking-tight">
              You placed out of {placed} concept{placed === 1 ? "" : "s"}
            </h1>
            <p className="text-muted-foreground">Thanks! Your learning map has been updated.</p>
          </div>
          <List
            title="Learned"
            hint="You can skip these and go straight to what's next."
            concepts={result.data.learned}
          />
          <List
            title="To check soon"
            hint="Counted as learned. A quick review will come up soon to make sure."
            concepts={result.data.conditional}
          />
          <List
            title="To learn"
            hint="These are back to learn, one lesson at a time."
            concepts={result.data.to_learn}
          />
          <div className="flex flex-wrap gap-3">
            {course && (
              <Button asChild>
                <Link to={`/learn/${course.slug}`}>See your knowledge map</Link>
              </Button>
            )}
            <Button asChild variant="outline">
              <Link to="/">Back home</Link>
            </Button>
          </div>
        </>
      )}
    </main>
  );
}
