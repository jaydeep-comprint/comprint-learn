import { useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, CheckCircle2, RotateCcw } from "lucide-react";
import { useCallback, useState } from "react";
import { Link, useParams } from "react-router";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  learnKeys,
  postProgress,
  submitRemediationAnswer,
  useRemediation,
  useRemediationQuestion,
} from "@/features/learn/api";
import { conceptCourse, lessonPath } from "@/features/learn/paths";
import { PracticeRunner } from "@/features/learn/PracticeRunner";
import { useStepTimer } from "@/features/learn/useStepTimer";
import { ApiError } from "@/lib/api";
import type { AnswerResult, RemediationInfo } from "@/lib/types";
import { NotFoundPage } from "@/pages/NotFoundPage";

const STEP = "remediation"; // study time is logged against the prerequisite as practice

function Outcome({
  info,
  passed,
  kpOpen = true,
}: {
  info: RemediationInfo;
  passed: boolean;
  /** False when another brush-up still blocks the part. */
  kpOpen?: boolean;
}) {
  const concept = info.concept;
  const prereq = info.prereq;
  return (
    <div className="flex flex-col items-center gap-4 py-8 text-center">
      {passed ? (
        <>
          <CheckCircle2 className="size-10 text-[var(--success)]" aria-hidden />
          <h2 className="text-2xl font-semibold">
            {kpOpen
              ? `Nice, ${info.kp_title} is open again`
              : `Nice. ${info.kp_title} opens once your other brush-ups are done`}
          </h2>
          <Button asChild className="w-full sm:w-auto">
            <Link to={lessonPath(conceptCourse(concept.id), concept.id)}>
              Back to {concept.title}
            </Link>
          </Button>
        </>
      ) : (
        <>
          <RotateCcw className="size-10 text-[var(--warning)]" aria-hidden />
          <h2 className="text-2xl font-semibold">Let&apos;s relearn {prereq.title} first</h2>
          <Button asChild className="w-full sm:w-auto">
            <Link to={lessonPath(conceptCourse(prereq.id), prereq.id)}>Relearn {prereq.title}</Link>
          </Button>
        </>
      )}
      <Button asChild variant="outline" className="w-full sm:w-auto">
        <Link to="/">Home</Link>
      </Button>
    </div>
  );
}

function Review({ info }: { info: RemediationInfo }) {
  const queryClient = useQueryClient();
  const [done, setDone] = useState<AnswerResult | null>(null);
  const query = useRemediationQuestion(info.id);
  const report = useCallback(
    (step: string, seconds: number, opts: { keepalive: boolean }) =>
      void postProgress(info.prereq.id, step, seconds, opts),
    [info.prereq.id],
  );
  useStepTimer(done ? null : STEP, report);

  if (done) {
    return (
      <Outcome
        info={info}
        passed={done.session_status === "passed"}
        kpOpen={done.kp_open !== false}
      />
    );
  }
  return (
    <PracticeRunner
      tutor
      header={`Brush up · ${info.prereq.title}`}
      query={query}
      submit={(body) => submitRemediationAnswer(info.id, body)}
      onDone={(r) => {
        setDone(r);
        void queryClient.invalidateQueries({ queryKey: learnKeys.all });
      }}
      renderConflict={() => (
        <p className="rounded-lg border p-4">This brush-up isn&apos;t due any more.</p>
      )}
    />
  );
}

/** `/learn/brush-up/:id`: a short review of a key prerequisite after repeated fails. */
export function RemediationPage() {
  const { id = "" } = useParams();
  const info = useRemediation(id);

  if (info.isPending) {
    return (
      <div className="mx-auto max-w-prose space-y-3" aria-busy="true">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-4 w-full" />
      </div>
    );
  }
  if (info.isError) {
    if (info.error instanceof ApiError && [403, 404].includes(info.error.status)) {
      return <NotFoundPage />;
    }
    return (
      <div className="mx-auto flex max-w-prose flex-col items-center gap-3 py-8 text-center">
        <AlertCircle className="size-8 text-muted-foreground" aria-hidden />
        <p>Couldn&apos;t load this brush-up.</p>
        <Button variant="outline" onClick={() => info.refetch()}>
          Try again
        </Button>
      </div>
    );
  }
  const data = info.data;
  const prereqLesson = lessonPath(conceptCourse(data.prereq.id), data.prereq.id);
  return (
    <div className="mx-auto max-w-prose">
      <Button asChild variant="ghost" size="sm" className="mb-2 -ml-2">
        <Link to="/">
          <ArrowLeft aria-hidden />
          Home
        </Link>
      </Button>
      <header className="mb-6 space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Brush up: {data.prereq.title}</h1>
        <p className="text-muted-foreground">Needed for {data.concept.title}</p>
        <Link to={prereqLesson} className="text-sm underline underline-offset-4">
          Look back at the lesson
        </Link>
      </header>
      {data.state === "review_due" ? (
        <Review info={data} />
      ) : data.state === "relearn" ? (
        <Outcome info={data} passed={false} />
      ) : (
        <Outcome info={data} passed />
      )}
    </div>
  );
}
