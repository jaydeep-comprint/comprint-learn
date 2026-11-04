import { PartyPopper } from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { lessonPath } from "@/features/learn/paths";
import type { ConceptRef } from "@/lib/types";

/** "Concept learned ✓" and the concepts it unlocked (null: not known, e.g. staff preview). */
export function LearnedScreen({
  course,
  title,
  unlocked,
  preview = false,
}: {
  course: string;
  title: string;
  unlocked: ConceptRef[] | null;
  preview?: boolean;
}) {
  return (
    <div className="flex flex-col items-center gap-4 py-10 text-center">
      <PartyPopper className="size-10 text-[var(--success)]" aria-hidden />
      <div className="space-y-1">
        <h2 className="text-2xl font-semibold">
          {preview ? "End of the lesson" : "Concept learned ✓"}
        </h2>
        <p className="text-muted-foreground">{title}</p>
      </div>
      {unlocked !== null && (
        <div className="w-full max-w-sm space-y-2">
          {unlocked.length === 0 ? (
            <p className="text-muted-foreground">Nothing new unlocked</p>
          ) : (
            <>
              <p className="font-medium">You unlocked:</p>
              {unlocked.map((c) => (
                <Button key={c.id} asChild className="w-full">
                  <Link to={lessonPath(course, c.id)}>{c.title}</Link>
                </Button>
              ))}
            </>
          )}
        </div>
      )}
      <Button asChild variant="outline" className="w-full sm:w-auto">
        <Link to={`/learn/${course}`}>Back to course</Link>
      </Button>
    </div>
  );
}
