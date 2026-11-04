import { useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Eye } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";

import { Markdown } from "@/components/markdown/Markdown";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  learnKeys,
  lockedPrereqs,
  postProgress,
  useLesson,
  useSubmitCheck,
} from "@/features/learn/api";
import { CheckStep } from "@/features/learn/CheckStep";
import { FinishedScreen } from "@/features/learn/FinishedScreen";
import { LockedPanel } from "@/features/learn/LockedPanel";
import { StepIndicator } from "@/features/learn/StepIndicator";
import { useStepTimer } from "@/features/learn/useStepTimer";
import { ApiError } from "@/lib/api";
import type { CheckResult, Lesson } from "@/lib/types";
import { NotFoundPage } from "@/pages/NotFoundPage";

function initialIndex(lesson: Lesson): number {
  const p = lesson.progress;
  if (lesson.preview || !p || p.finished_at) return 0; // preview and review mode start at intro
  return Math.max(0, lesson.steps.indexOf(p.last_step));
}

function furthestSeen(lesson: Lesson): number {
  const seen = new Set(lesson.progress?.seen_steps ?? []);
  return lesson.steps.reduce((max, step, i) => (seen.has(step) ? i : max), 0);
}

function LessonHeader({
  course,
  title,
  children,
}: {
  course: string;
  title: string | null;
  children?: ReactNode;
}) {
  return (
    <header className="mx-auto mb-6 max-w-prose space-y-3">
      <Button asChild variant="ghost" size="sm" className="-ml-2">
        <Link to={`/learn/${course}`}>
          <ArrowLeft aria-hidden />
          Course
        </Link>
      </Button>
      {title ? (
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      ) : (
        <Skeleton className="h-8 w-2/3" />
      )}
      {children}
    </header>
  );
}

function LessonView({ course, lesson }: { course: string; lesson: Lesson }) {
  const queryClient = useQueryClient();
  const { steps, preview } = lesson;
  const review = !preview && !!lesson.progress?.finished_at;
  const allOpen = preview || review;

  const [index, setIndex] = useState(() => initialIndex(lesson));
  const [furthest, setFurthest] = useState(() =>
    Math.max(furthestSeen(lesson), initialIndex(lesson)),
  );
  const [result, setResult] = useState<CheckResult | null>(lesson.check_result);
  const [finished, setFinished] = useState(false);
  const submit = useSubmitCheck(lesson.id);
  const checkShownAt = useRef<number | null>(null);
  const lastPost = useRef<Promise<unknown>>(Promise.resolve());
  const topRef = useRef<HTMLDivElement>(null);

  const step = steps[index] ?? "intro";
  const checkIndex = steps.indexOf("check");
  const checkPending = checkIndex >= 0 && result === null;
  // Jump up to the furthest step reached + 1, but never past an unanswered check.
  const maxIndex = allOpen
    ? steps.length - 1
    : Math.min(steps.length - 1, checkPending && furthest >= checkIndex ? furthest : furthest + 1);
  const studentBlockedByCheck = !preview && checkPending && index >= checkIndex;
  const isLast = index === steps.length - 1;

  const report = useCallback(
    (s: string, seconds: number, opts: { keepalive: boolean }) =>
      void postProgress(lesson.id, s, seconds, opts),
    [lesson.id],
  );
  // Declared before the "seen" effect: leaving a step reports its time before the next is marked.
  useStepTimer(preview || finished ? null : step, report);

  useEffect(() => {
    if (finished) return;
    topRef.current?.scrollIntoView?.({ block: "start" });
    if (step === "check") checkShownAt.current = performance.now();
    if (!preview) lastPost.current = postProgress(lesson.id, step, 0);
  }, [finished, lesson.id, preview, step]);

  const go = (i: number) => {
    setIndex(i);
    setFurthest((f) => Math.max(f, i));
  };

  const finish = () => {
    setFinished(true);
    // Statuses and "Continue" changed; refetch what shows them once the last step's post landed.
    void lastPost.current.finally(() => queryClient.invalidateQueries({ queryKey: learnKeys.all }));
  };

  const onSubmit = (optionId: string) => {
    const started = checkShownAt.current ?? performance.now();
    submit.mutate(
      { option_id: optionId, time_taken_ms: Math.round(performance.now() - started) },
      {
        onSuccess: (r) => setResult(r),
        onError: () => toast.error("Couldn't submit, try again"),
      },
    );
  };

  if (finished) {
    return (
      <>
        <LessonHeader course={course} title={lesson.title} />
        <FinishedScreen
          course={course}
          conceptId={lesson.id}
          title={lesson.title}
          preview={preview}
        />
      </>
    );
  }

  const kpIndex = steps.slice(0, index + 1).filter((s) => s.startsWith("kp:")).length;
  const kp = step.startsWith("kp:") ? lesson.kps.find((k) => `kp:${k.slug}` === step) : undefined;

  return (
    <div ref={topRef} className="scroll-mt-20">
      <LessonHeader course={course} title={lesson.title}>
        <StepIndicator steps={steps} current={index} maxIndex={maxIndex} onJump={go} />
      </LessonHeader>
      {preview && (
        <p className="mx-auto mb-4 flex max-w-prose items-center gap-2 rounded-md bg-muted px-3 py-2 text-sm">
          <Eye className="size-4" aria-hidden />
          Teacher preview: nothing is saved
        </p>
      )}
      {review && (
        <p className="mx-auto mb-4 max-w-prose text-sm text-muted-foreground">
          You&apos;ve finished this lesson. Every step is open for review.
        </p>
      )}
      <article className="mx-auto max-w-prose pb-4">
        {step === "intro" && <Markdown assetBase={lesson.asset_base}>{lesson.intro_md}</Markdown>}
        {step === "check" && lesson.check && (
          <CheckStep
            check={lesson.check}
            result={result}
            assetBase={lesson.asset_base}
            submitting={submit.isPending}
            onSubmit={onSubmit}
          />
        )}
        {kp && (
          <div className="space-y-4">
            <p className="text-sm font-semibold text-muted-foreground">
              Worked example {kpIndex} of {lesson.kps.length} · {kp.title}
            </p>
            <Markdown assetBase={lesson.asset_base}>{kp.worked_example_md}</Markdown>
          </div>
        )}
      </article>
      <div className="sticky bottom-0 -mx-4 mt-6 border-t bg-background/95 px-4 py-3 backdrop-blur sm:static sm:mx-0 sm:bg-transparent sm:px-0 sm:backdrop-blur-none">
        <div className="mx-auto flex max-w-prose items-center justify-between gap-3">
          <Button variant="outline" onClick={() => go(index - 1)} disabled={index === 0}>
            Back
          </Button>
          {isLast ? (
            <Button onClick={finish} disabled={studentBlockedByCheck}>
              Finish lesson
            </Button>
          ) : (
            <Button
              onClick={() => go(index + 1)}
              disabled={studentBlockedByCheck && index === checkIndex}
            >
              Next
            </Button>
          )}
        </div>
        {isLast && studentBlockedByCheck && (
          <p className="mx-auto mt-2 max-w-prose text-sm text-muted-foreground">
            Answer the quick check first.
          </p>
        )}
      </div>
    </div>
  );
}

export function LessonPage() {
  const { course = "", conceptCourse = "", conceptSlug = "" } = useParams();
  const ref = `${conceptCourse}/${conceptSlug}`;
  const lesson = useLesson(ref);

  // Wait for this visit's fetch: a cached copy may predate progress made since (resume point).
  if (lesson.isPending || (lesson.isFetching && !lesson.isFetchedAfterMount)) {
    return (
      <div aria-busy="true">
        <LessonHeader course={course} title={null} />
        <div className="mx-auto max-w-prose space-y-3">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
          <Skeleton className="h-4 w-4/6" />
        </div>
      </div>
    );
  }
  if (lesson.isError) {
    const prereqs = lockedPrereqs(lesson.error);
    if (prereqs) {
      return (
        <div>
          <LessonHeader course={course} title="Finish these first" />
          <div className="mx-auto max-w-prose">
            <LockedPanel course={course} prereqs={prereqs} />
          </div>
        </div>
      );
    }
    if (lesson.error instanceof ApiError && lesson.error.status === 404) return <NotFoundPage />;
    return (
      <div>
        <LessonHeader course={course} title="Lesson" />
        <div className="mx-auto flex max-w-prose flex-col items-center gap-3 py-8 text-center">
          <AlertCircle className="size-8 text-muted-foreground" aria-hidden />
          <p>Couldn&apos;t load this lesson.</p>
          <Button variant="outline" onClick={() => lesson.refetch()}>
            Try again
          </Button>
        </div>
      </div>
    );
  }
  return <LessonView key={ref} course={course} lesson={lesson.data} />;
}
