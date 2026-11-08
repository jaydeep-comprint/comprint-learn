import { Link } from "react-router";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { AssignmentDraft } from "@/features/assignments/AssignmentDialog";
import type { SummaryFact, SummaryNote } from "@/lib/types";

import { ClaimText } from "./CitationChip";
import { resourceHref, resourceLabel } from "./links";

const OTHER_COURSE = "This prerequisite is in another course";

/** Re-teaching notes (class) or the one suggestion (student), with Assign buttons. */
export function NoteList({
  notes,
  facts,
  kind,
  classCourse,
  hrefFor,
  onAssign,
}: {
  notes: SummaryNote[];
  facts: SummaryFact[];
  kind: "class" | "student";
  classCourse: string | undefined;
  hrefFor: (fact: SummaryFact) => string | null;
  onAssign: (draft: AssignmentDraft) => void;
}) {
  if (notes.length === 0) return null;
  return (
    <section className="space-y-3">
      <h3 className="text-sm font-semibold">
        {kind === "student" ? "Suggestion" : "Re-teaching notes"}
      </h3>
      <ol className="space-y-4">
        {notes.map((note, i) => {
          const canAssign = note.assign.concepts.length > 0;
          const assign = (studentIds: string[] | null) =>
            onAssign({ concepts: note.assign.concepts, student_ids: studentIds });
          return (
            <li key={i} className="space-y-2 rounded-md border p-3 text-sm">
              <p className="font-medium">{note.focus}</p>
              <p className="text-muted-foreground">
                <ClaimText
                  text={note.why.text}
                  citations={note.why.citations}
                  facts={facts}
                  hrefFor={hrefFor}
                />
              </p>
              {note.revisit.length > 0 && (
                <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                  <span className="text-muted-foreground">Revisit:</span>
                  {note.revisit.map((r) => {
                    const href = resourceHref(r, classCourse);
                    return href ? (
                      <Link key={r.id} to={href} className="underline underline-offset-2">
                        {resourceLabel(r)}
                      </Link>
                    ) : (
                      <span key={r.id}>{resourceLabel(r)}</span>
                    );
                  })}
                </p>
              )}
              {note.group.length > 0 && (
                <p className="flex flex-wrap items-center gap-1">
                  <span className="mr-1 text-muted-foreground">Group:</span>
                  {note.group.map((g) => (
                    <Badge key={g.student_id} variant="secondary">
                      {g.display_name}
                    </Badge>
                  ))}
                </p>
              )}
              <div className="flex flex-wrap items-center gap-2 pt-1">
                {kind === "student" ? (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!canAssign || note.assign.student_ids?.length === 0}
                    onClick={() => assign(note.assign.student_ids)}
                  >
                    Assign this
                  </Button>
                ) : (
                  <>
                    {note.group.length > 0 && (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!canAssign}
                        onClick={() => assign(note.assign.student_ids)}
                      >
                        Assign to these students
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!canAssign}
                      onClick={() => assign(null)}
                    >
                      Assign to class
                    </Button>
                  </>
                )}
                {!canAssign && (
                  <span className="text-xs text-muted-foreground">{OTHER_COURSE}</span>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
