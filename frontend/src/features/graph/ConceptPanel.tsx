import { X } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { LockedPanel } from "@/features/learn/LockedPanel";
import {
  brushUpPath,
  lessonPath,
  placedLabel,
  STATUS_LABELS,
  unfinishedPrereqs,
} from "@/features/learn/paths";
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

/** Read-only details for a teacher's view of a student's map (spec 010): no lesson buttons. */
export type PanelDetails = (concept: OutlineConcept) => ReactNode;

function Body({
  course,
  outline,
  concept,
  details,
}: {
  course: string;
  outline: Outline;
  concept: OutlineConcept;
  details?: PanelDetails;
}) {
  const part = Math.min(concept.parts_passed + 1, concept.parts_total);
  const onPractice =
    concept.parts_total > concept.kps_total && concept.kps_passed === concept.kps_total;
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{concept.summary}</p>
      {concept.status && (
        <p className="flex items-center gap-2 text-sm">
          <StatusIcon status={concept.status} />
          {STATUS_LABELS[concept.status]}
          {placedLabel(concept) && (
            <span className="text-muted-foreground">· {placedLabel(concept)}</span>
          )}
          {concept.status === "in_progress" && concept.parts_total > 0 && (
            <span className="text-muted-foreground">
              · {onPractice ? "Practice left" : `Part ${part} of ${concept.parts_total}`}
            </span>
          )}
        </p>
      )}
      {details ? (
        details(concept)
      ) : (
        <>
          {concept.waiting && (
            <p className="text-sm">Retry tomorrow, or after you learn something else.</p>
          )}
          {concept.status === "locked" && (
            <LockedPanel course={course} prereqs={unfinishedPrereqs(outline, concept)} />
          )}
          <Action course={course} concept={concept} />
        </>
      )}
    </div>
  );
}

/** The selected concept: a side panel on desktop, a bottom sheet on phones. */
export function ConceptPanel({
  course,
  outline,
  concept,
  onClose,
  details,
}: {
  course: string;
  outline: Outline;
  concept: OutlineConcept | null;
  onClose: () => void;
  details?: PanelDetails;
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
        <Body course={course} outline={outline} concept={concept} details={details} />
      </aside>
    );
  }
  return (
    <Sheet open={concept !== null} onOpenChange={(open) => !open && onClose()} modal={false}>
      <SheetContent side="bottom" className="p-4 pb-6">
        <SheetTitle className="pr-8">{concept?.title}</SheetTitle>
        <SheetDescription className="sr-only">Concept details</SheetDescription>
        {concept && <Body course={course} outline={outline} concept={concept} details={details} />}
      </SheetContent>
    </Sheet>
  );
}
