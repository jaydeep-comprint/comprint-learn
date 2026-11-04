import { PartyPopper } from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { useOutline } from "@/features/learn/api";
import { lessonPath } from "@/features/learn/paths";

export function FinishedScreen({
  course,
  conceptId,
  title,
  preview,
}: {
  course: string;
  conceptId: string;
  title: string;
  preview: boolean;
}) {
  const outline = useOutline(course);
  const concepts = outline.data?.chapters.flatMap((ch) => ch.concepts) ?? [];
  const index = concepts.findIndex((c) => c.id === conceptId);
  const next = preview
    ? concepts[index + 1]
    : concepts.find(
        (c) => c.id !== conceptId && (c.status === "ready" || c.status === "in_progress"),
      );
  const allDone = !preview && concepts.length > 0 && concepts.every((c) => c.status === "finished");

  return (
    <div className="flex flex-col items-center gap-4 py-10 text-center">
      <PartyPopper className="size-10 text-[var(--success)]" aria-hidden />
      <div className="space-y-1">
        <h2 className="text-2xl font-semibold">Lesson finished</h2>
        <p className="text-muted-foreground">{title}</p>
      </div>
      {outline.isSuccess && next && (
        <Button asChild className="w-full sm:w-auto">
          <Link to={lessonPath(course, next.id)}>Next up: {next.title}</Link>
        </Button>
      )}
      {outline.isSuccess && !next && allDone && (
        <p className="font-medium">You&apos;ve finished every lesson in this course</p>
      )}
      <Button asChild variant="outline" className="w-full sm:w-auto">
        <Link to={`/learn/${course}`}>Back to course</Link>
      </Button>
    </div>
  );
}
