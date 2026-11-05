import { AlertCircle, Copy, RefreshCw, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { AssignmentDraft } from "@/features/assignments/AssignmentDialog";
import type { DashboardWindow, SummaryFact, SummaryState } from "@/lib/types";

import { BLOCKED_REASONS, generateError, useGenerateSummary, useSummaryState } from "./api";
import { ClaimText } from "./CitationChip";
import { copyText, timeAgo } from "./copyText";
import { factHref } from "./links";
import { NoteList } from "./NoteList";

const WINDOW_LABELS: Record<DashboardWindow, string> = {
  "7d": "Last 7 days",
  "30d": "Last 30 days",
  all: "All time",
};

const NOT_ENOUGH = "Not enough activity yet for a useful summary. Check back after a few lessons.";

/** Spec 011: the AI summary card on the class Overview (or a student's page). Its errors never
 * blank the rest of the page; it hides itself when teacher AI is switched off. */
export function SummaryCard({
  classId,
  window,
  studentId,
  classCourse,
  onAssign,
}: {
  classId: string;
  window: DashboardWindow;
  studentId?: string;
  classCourse: string | undefined;
  onAssign: (draft: AssignmentDraft) => void;
}) {
  const target = { classId, window, studentId };
  const query = useSummaryState(target);
  const generate = useGenerateSummary(target);
  const student = studentId !== undefined;
  const title = student ? "Summary" : `AI summary · ${WINDOW_LABELS[window]}`;
  const state = query.data;

  if (state && !state.enabled) return null;

  const regenerate = state ? <GenerateButton state={state} generate={generate} /> : null;
  return (
    <Card id="summary" aria-labelledby={`summary-title-${studentId ?? window}`}>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-2">
        <div className="space-y-1">
          <CardTitle
            id={`summary-title-${studentId ?? window}`}
            className="flex items-center gap-2"
          >
            <Sparkles className="size-4 text-muted-foreground" aria-hidden />
            {title}
            {state?.summary && state.stale && <Badge variant="outline">Data changed</Badge>}
          </CardTitle>
          {state?.summary && (
            <CardDescription>
              by {state.summary.created_by_name} · {timeAgo(state.summary.created_at)}
            </CardDescription>
          )}
        </div>
        {state?.summary && (
          <div className="flex flex-wrap items-center gap-2">
            {regenerate}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                if (!state.summary) return;
                void navigator.clipboard
                  ?.writeText(copyText(state.summary))
                  .then(() => toast.success("Summary copied."))
                  .catch(() => toast.error("Couldn't copy."));
              }}
            >
              <Copy aria-hidden />
              Copy
            </Button>
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {query.isPending ? (
          <Lines />
        ) : query.isError || !state ? (
          <div role="alert" className="flex items-center gap-3 text-sm">
            <AlertCircle className="size-4 text-destructive" aria-hidden />
            <span>Couldn&apos;t load this.</span>
            <Button variant="outline" size="sm" onClick={() => void query.refetch()}>
              Try again
            </Button>
          </div>
        ) : (
          <Body
            state={state}
            classId={classId}
            window={window}
            studentId={studentId}
            classCourse={classCourse}
            onAssign={onAssign}
            writing={generate.isPending}
            error={generate.isError ? generateError(generate.error) : null}
            onRetry={() => generate.mutate()}
            regenerate={regenerate}
          />
        )}
      </CardContent>
    </Card>
  );
}

function Lines() {
  return (
    <div className="space-y-2" aria-busy="true">
      <Skeleton className="h-5" />
      <Skeleton className="h-5" />
      <Skeleton className="h-5 w-2/3" />
    </div>
  );
}

function GenerateButton({
  state,
  generate,
}: {
  state: SummaryState;
  generate: ReturnType<typeof useGenerateSummary>;
}) {
  const reason = state.blocked ? BLOCKED_REASONS[state.blocked] : undefined;
  const label = state.summary ? "Regenerate" : "Generate summary";
  return (
    <span className="inline-flex flex-col items-end gap-0.5">
      <Button
        size="sm"
        variant={state.summary ? "outline" : "default"}
        disabled={!state.can_regenerate || generate.isPending}
        title={reason}
        onClick={() => generate.mutate()}
      >
        {state.summary ? <RefreshCw aria-hidden /> : <Sparkles aria-hidden />}
        {label}
      </Button>
      {reason && state.summary && <span className="text-xs text-muted-foreground">{reason}</span>}
    </span>
  );
}

function Body({
  state,
  classId,
  window,
  studentId,
  classCourse,
  onAssign,
  writing,
  error,
  onRetry,
  regenerate,
}: {
  state: SummaryState;
  classId: string;
  window: DashboardWindow;
  studentId?: string;
  classCourse: string | undefined;
  onAssign: (draft: AssignmentDraft) => void;
  writing: boolean;
  error: string | null;
  onRetry: () => void;
  regenerate: React.ReactNode;
}) {
  const summary = state.summary;
  const hrefFor = (fact: SummaryFact) => factHref(fact.link, { classId, window, studentId });
  const errorBox = error && (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 rounded-md border border-destructive/40 p-3 text-sm"
    >
      <AlertCircle className="size-4 text-destructive" aria-hidden />
      <span>{error}</span>
      {!summary && state.can_regenerate && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
  const writingBox = writing && (
    <div className="space-y-2" aria-live="polite">
      <p className="text-sm text-muted-foreground">Writing… this can take up to a minute.</p>
      <Lines />
    </div>
  );

  if (!summary) {
    if (!state.enough_data) {
      return <p className="text-sm text-muted-foreground">{NOT_ENOUGH}</p>;
    }
    return (
      <div className="space-y-3">
        {errorBox}
        {writingBox || (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-muted-foreground">
              {studentId
                ? "Get a short written summary of this student's week, with one suggestion."
                : "Get a short written summary of this week, with re-teaching ideas."}
            </p>
            {regenerate}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {errorBox}
      {writingBox}
      {summary.status === "partial" && (
        <p className="text-xs text-muted-foreground">
          Some sentences were removed because they couldn&apos;t be checked against the data.
        </p>
      )}
      <ul className="list-disc space-y-2 pl-5 text-sm">
        {summary.claims.map((c, i) => (
          <li key={i}>
            <ClaimText
              text={c.text}
              citations={c.citations}
              facts={summary.facts}
              hrefFor={hrefFor}
            />
          </li>
        ))}
      </ul>
      <NoteList
        notes={summary.notes}
        facts={summary.facts}
        kind={summary.kind}
        classCourse={classCourse}
        hrefFor={hrefFor}
        onAssign={onAssign}
      />
      <p className="text-xs text-muted-foreground">
        Written by AI from the dashboard numbers. Every sentence links to its source; check before
        acting.
      </p>
    </div>
  );
}
