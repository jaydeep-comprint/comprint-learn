import { X } from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { LockedPanel } from "@/features/learn/LockedPanel";
import { brushUpPath, lessonPath, STATUS_LABELS, unfinishedPrereqs } from "@/features/learn/paths";
import { StatusIcon } from "@/features/learn/StatusIcon";
import type { Outline, OutlineConcept } from "@/lib/types";
import { useMediaQuery } from "@/lib/useMediaQuery";

function Action({ course, concept }: { course: string; concept: OutlineConcept }) {
  const to =
    concept.brush_up && concept.brush_up_id
      ? brushUpPath(concept.brush_up_id)
      : lessonPath(course, concept.id);
  const label =
    concept.status === null
      ? "Preview lesson"
      : concept.brush_up
        ? "Brush up first"
        : concept.status === "learned"
          ? "Review"
          : concept.status === "in_progress"
            ? "Continue"
            : "Start";
  if (concept.status === "locked") {
    return (
      <Button disabled className="w-full">
        Locked
      </Button>
    );
  }
  return (
    <Button asChild className="w-full">
      <Link to={to}>{label}</Link>
    </Button>
  );
}

function Body({
  course,
  outline,
  concept,
}: {
  course: string;
  outline: Outline;
  concept: OutlineConcept;
}) {
  const part = Math.min(concept.kps_passed + 1, concept.kps_total);
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{concept.summary}</p>
      {concept.status && (
        <p className="flex items-center gap-2 text-sm">
          <StatusIcon status={concept.status} />
          {STATUS_LABELS[concept.status]}
          {concept.status === "in_progress" && concept.kps_total > 0 && (
            <span className="text-muted-foreground">
              · Part {part} of {concept.kps_total}
            </span>
          )}
        </p>
      )}
      {concept.waiting && (
        <p className="text-sm">Retry tomorrow, or after you learn something else.</p>
      )}
      {concept.status === "locked" && (
        <LockedPanel course={course} prereqs={unfinishedPrereqs(outline, concept)} />
      )}
      <Action course={course} concept={concept} />
    </div>
  );
}

/** The selected concept: a side panel on desktop, a bottom sheet on phones. */
export function ConceptPanel({
  course,
  outline,
  concept,
  onClose,
}: {
  course: string;
  outline: Outline;
  concept: OutlineConcept | null;
  onClose: () => void;
}) {
  const desktop = useMediaQuery("(min-width: 768px)");
  if (desktop) {
    if (!concept) return null;
    return (
      <aside
        aria-label={concept.title}
        className="absolute top-3 right-3 bottom-3 z-10 w-80 space-y-3 overflow-y-auto rounded-lg border bg-background p-4 shadow-lg"
      >
        <div className="flex items-start justify-between gap-2">
          <h2 className="text-lg font-semibold">{concept.title}</h2>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close">
            <X aria-hidden />
          </Button>
        </div>
        <Body course={course} outline={outline} concept={concept} />
      </aside>
    );
  }
  return (
    <Sheet open={concept !== null} onOpenChange={(open) => !open && onClose()} modal={false}>
      <SheetContent side="bottom" className="p-4 pb-6">
        <SheetTitle className="pr-8">{concept?.title}</SheetTitle>
        <SheetDescription className="sr-only">Concept details</SheetDescription>
        {concept && <Body course={course} outline={outline} concept={concept} />}
      </SheetContent>
    </Sheet>
  );
}
