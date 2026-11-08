import { AlertCircle, ArrowLeft, ChevronRight, Clock, RotateCcw } from "lucide-react";
import { lazy, Suspense, useState } from "react";
import { Link, useParams } from "react-router";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { useOutline } from "@/features/learn/api";
import { LockedPanel } from "@/features/learn/LockedPanel";
import { lessonPath, placedLabel, unfinishedPrereqs } from "@/features/learn/paths";
import { ProgressBar } from "@/features/learn/ProgressBar";
import { StatusIcon } from "@/features/learn/StatusIcon";
import { ApiError } from "@/lib/api";
import type { LockedPrereq, OutlineConcept } from "@/lib/types";
import { useMediaQuery } from "@/lib/useMediaQuery";
import { cn } from "@/lib/utils";
import { NotFoundPage } from "@/pages/NotFoundPage";

// React Flow loads only when the Map is shown.
const CourseMap = lazy(() => import("@/features/graph/CourseMap"));

type View = "list" | "map";
const VIEW_KEY = "learn.courseView";

function storedView(): View | null {
  try {
    const v = window.localStorage.getItem(VIEW_KEY);
    return v === "list" || v === "map" ? v : null;
  } catch {
    return null;
  }
}

function storeView(view: View): void {
  try {
    window.localStorage.setItem(VIEW_KEY, view);
  } catch {
    // Private mode or blocked storage: the choice just isn't remembered.
  }
}

/** List | Map: the stored choice, else Map on >= 768 px and List below. */
function useCourseView(): [View, (v: View) => void] {
  const wide = useMediaQuery("(min-width: 768px)");
  const [chosen, setChosen] = useState<View | null>(storedView);
  const set = (v: View) => {
    storeView(v);
    setChosen(v);
  };
  return [chosen ?? (wide ? "map" : "list"), set];
}

function ViewToggle({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  return (
    <div role="group" aria-label="View" className="inline-flex rounded-md border p-0.5">
      {(["list", "map"] as const).map((v) => (
        <button
          key={v}
          type="button"
          aria-pressed={view === v}
          onClick={() => onChange(v)}
          className={cn(
            "min-h-9 rounded px-3 text-sm font-medium",
            view === v ? "bg-primary text-primary-foreground" : "hover:bg-muted",
          )}
        >
          {v === "list" ? "List" : "Map"}
        </button>
      ))}
    </div>
  );
}

function LockedSheet({
  course,
  concept,
  prereqs,
  onClose,
}: {
  course: string;
  concept: OutlineConcept | null;
  prereqs: LockedPrereq[];
  onClose: () => void;
}) {
  const desktop = useMediaQuery("(min-width: 640px)");
  const open = concept !== null;
  const onOpenChange = (next: boolean) => !next && onClose();
  const panel = <LockedPanel course={course} prereqs={prereqs} />;
  if (desktop) {
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Learn these first</DialogTitle>
            <DialogDescription>{concept?.title}</DialogDescription>
          </DialogHeader>
          {panel}
        </DialogContent>
      </Dialog>
    );
  }
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="bottom" className="p-4 pb-6">
        <div className="space-y-1 pr-8">
          <SheetTitle>Learn these first</SheetTitle>
          <SheetDescription className="text-sm text-muted-foreground">
            {concept?.title}
          </SheetDescription>
        </div>
        {panel}
      </SheetContent>
    </Sheet>
  );
}

function ConceptRow({
  course,
  concept,
  onLocked,
}: {
  course: string;
  concept: OutlineConcept;
  onLocked: (c: OutlineConcept) => void;
}) {
  const body = (
    <>
      {concept.status && <StatusIcon status={concept.status} className="mt-0.5" />}
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2 font-medium">
          {concept.title}
          {concept.status === "in_progress" && concept.parts_total > 0 && (
            <span className="text-sm font-normal text-muted-foreground">
              {concept.parts_passed}/{concept.parts_total}
            </span>
          )}
          {concept.waiting && (
            <Badge variant="outline" className="gap-1">
              <Clock className="size-3" aria-hidden />
              Waiting
            </Badge>
          )}
          {concept.brush_up && (
            <Badge variant="outline" className="gap-1">
              <RotateCcw className="size-3" aria-hidden />
              Brush up
            </Badge>
          )}
          {placedLabel(concept) && <Badge variant="secondary">{placedLabel(concept)}</Badge>}
        </span>
        <span className="block truncate text-sm text-muted-foreground">{concept.summary}</span>
      </span>
      <ChevronRight className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
    </>
  );
  const rowClass = "flex min-h-14 w-full items-start gap-3 p-3 text-left hover:bg-muted";
  if (concept.status === "locked") {
    return (
      <button type="button" className={rowClass} onClick={() => onLocked(concept)}>
        {body}
      </button>
    );
  }
  return (
    <Link to={lessonPath(course, concept.id)} className={rowClass}>
      {body}
    </Link>
  );
}

export function CoursePage() {
  const { course = "" } = useParams();
  const outline = useOutline(course);
  const [locked, setLocked] = useState<OutlineConcept | null>(null);
  const [view, setView] = useCourseView();

  if (outline.isPending) {
    return (
      <div className="mx-auto max-w-3xl space-y-4" aria-busy="true">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-2 w-full" />
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-14 w-full" />
        ))}
      </div>
    );
  }
  if (outline.isError) {
    if (outline.error instanceof ApiError && outline.error.status === 404) return <NotFoundPage />;
    return (
      <div className="mx-auto flex max-w-md flex-col items-center gap-3 py-12 text-center">
        <AlertCircle className="size-8 text-muted-foreground" aria-hidden />
        <p>Couldn&apos;t load this course.</p>
        <Button variant="outline" onClick={() => outline.refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  const data = outline.data;
  const concepts = data.chapters.flatMap((ch) => ch.concepts);
  const staff = concepts.every((c) => c.status === null);
  const learned = concepts.filter((c) => c.status === "learned").length;

  return (
    <div className="mx-auto max-w-3xl">
      <Button asChild variant="ghost" size="sm" className="mb-2 -ml-2">
        <Link to="/">
          <ArrowLeft aria-hidden />
          Home
        </Link>
      </Button>
      <h1 className="text-2xl font-semibold tracking-tight">{data.course.title}</h1>
      <div className="mt-3 mb-6">
        {staff ? (
          <p className="text-sm text-muted-foreground">
            Teacher preview: {concepts.length} lessons. Nothing you do here is saved.
          </p>
        ) : (
          <ProgressBar
            value={learned}
            total={concepts.length}
            label={`${learned} of ${concepts.length} concepts learned`}
          />
        )}
      </div>
      <div className="mb-4">
        <ViewToggle view={view} onChange={setView} />
      </div>
      {view === "map" ? (
        <Suspense fallback={<Skeleton className="h-[70vh] min-h-96 w-full" />}>
          <CourseMap course={course} outline={data} onShowList={() => setView("list")} />
        </Suspense>
      ) : (
        <div className="space-y-6">
          {data.chapters.map((ch) => (
            <section key={ch.slug} aria-labelledby={`chapter-${ch.slug}`}>
              <div className="mb-2 flex items-center gap-2">
                <h2 id={`chapter-${ch.slug}`} className="text-lg font-semibold">
                  {ch.title}
                </h2>
                {ch.grade && <Badge variant="outline">Class {ch.grade}</Badge>}
              </div>
              <ul className="divide-y rounded-lg border">
                {ch.concepts.map((c) => (
                  <li key={c.id}>
                    <ConceptRow course={course} concept={c} onLocked={setLocked} />
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
      <LockedSheet
        course={course}
        concept={locked}
        prereqs={locked ? unfinishedPrereqs(data, locked) : []}
        onClose={() => setLocked(null)}
      />
    </div>
  );
}
