import { Clock, RotateCcw } from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { useOutline } from "@/features/learn/api";
import { brushUpPath, conceptCourse, lessonPath } from "@/features/learn/paths";
import type { RemediationRef } from "@/lib/types";

/** The shared message of the failed screen and the waiting panel: come back later, or brush up
 * first; then up to 3 ready concepts to pick instead. */
export function ComeBackLater({
  course,
  kpTitle,
  remediations,
  exclude,
  heading,
}: {
  course: string;
  kpTitle: string;
  remediations: RemediationRef[];
  exclude: string;
  heading: string;
}) {
  const outline = useOutline(course);
  // A relearn blocks the part until the prerequisite is learned again, not just until tomorrow.
  const relearn = remediations.find((r) => r.kind === "relearn");
  const ready = (outline.data?.chapters.flatMap((ch) => ch.concepts) ?? [])
    .filter((c) => c.id !== exclude && (c.status === "ready" || c.status === "in_progress"))
    .slice(0, 3);
  return (
    <div className="flex flex-col items-center gap-4 py-8 text-center">
      <Clock className="size-10 text-muted-foreground" aria-hidden />
      <div className="space-y-2">
        <h2 className="text-2xl font-semibold">{heading}</h2>
        <p className="text-muted-foreground">
          {relearn
            ? `${kpTitle} reopens with new questions once you've relearned ${relearn.prereq.title}.`
            : `${kpTitle} will reopen with new questions tomorrow, or sooner once you learn something else.`}
        </p>
      </div>
      {remediations.map((r) =>
        r.kind === "review" ? (
          <Button key={r.id} asChild className="w-full sm:w-auto">
            <Link to={brushUpPath(r.id)}>
              <RotateCcw aria-hidden />
              First, brush up on {r.prereq.title}
            </Link>
          </Button>
        ) : (
          <Button key={r.id} asChild className="w-full sm:w-auto">
            <Link to={lessonPath(conceptCourse(r.prereq.id), r.prereq.id)}>
              <RotateCcw aria-hidden />
              First, relearn {r.prereq.title}
            </Link>
          </Button>
        ),
      )}
      <Button asChild variant="outline" className="w-full sm:w-auto">
        <Link to={`/learn/${course}`}>Back to course</Link>
      </Button>
      {ready.length > 0 && (
        <div className="w-full max-w-sm space-y-2 pt-2">
          <p className="text-sm font-medium text-muted-foreground">Or learn something else:</p>
          {ready.map((c) => (
            <Button key={c.id} asChild variant="ghost" className="w-full justify-start">
              <Link to={lessonPath(course, c.id)}>{c.title}</Link>
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}

export function FailedScreen(props: Omit<Parameters<typeof ComeBackLater>[0], "heading">) {
  return <ComeBackLater {...props} heading="Let's come back to this" />;
}
