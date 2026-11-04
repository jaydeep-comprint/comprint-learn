import { AlertCircle, ArrowLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
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
import { lessonPath, unfinishedPrereqs } from "@/features/learn/paths";
import { ProgressBar } from "@/features/learn/ProgressBar";
import { StatusIcon } from "@/features/learn/StatusIcon";
import { ApiError } from "@/lib/api";
import type { LockedPrereq, OutlineConcept } from "@/lib/types";
import { useMediaQuery } from "@/lib/useMediaQuery";
import { NotFoundPage } from "@/pages/NotFoundPage";

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
            <DialogTitle>Finish these first</DialogTitle>
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
          <SheetTitle>Finish these first</SheetTitle>
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
        <span className="block font-medium">{concept.title}</span>
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
  const finished = concepts.filter((c) => c.status === "finished").length;

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
            value={finished}
            total={concepts.length}
            label={`${finished} of ${concepts.length} concepts finished`}
          />
        )}
      </div>
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
      <LockedSheet
        course={course}
        concept={locked}
        prereqs={locked ? unfinishedPrereqs(data, locked) : []}
        onClose={() => setLocked(null)}
      />
    </div>
  );
}
