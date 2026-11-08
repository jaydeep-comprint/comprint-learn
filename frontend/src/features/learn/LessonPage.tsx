import { useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, CheckCircle2, Eye } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";

import { Markdown } from "@/components/markdown/Markdown";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  learnKeys,
  lockedPrereqs,
  postProgress,
  submitKpAnswer,
  useKpQuestion,
  useLesson,
  useSubmitCheck,
} from "@/features/learn/api";
import { CheckStep } from "@/features/learn/CheckStep";
import { FailedScreen } from "@/features/learn/FailedScreen";
import { LearnedScreen } from "@/features/learn/LearnedScreen";
import { LockedPanel } from "@/features/learn/LockedPanel";
import { PracticeRunner } from "@/features/learn/PracticeRunner";
import { PracticeStep } from "@/features/learn/PracticeStep";
import { StepIndicator } from "@/features/learn/StepIndicator";
import { useStepTimer } from "@/features/learn/useStepTimer";
import { WaitingPanel } from "@/features/learn/WaitingPanel";
import { pendingQuizId } from "@/features/quiz/api";
import { QuizPendingPanel } from "@/features/quiz/QuizPendingPanel";
import { ApiError } from "@/lib/api";
import type {
  AnswerResult,
  CheckResult,
  ConceptRef,
  Lesson,
  LessonKp,
  RemediationRef,
} from "@/lib/types";
import { NotFoundPage } from "@/pages/NotFoundPage";

/** The first step that isn't done: an active question session or practice attempt, the waiting
 * panel, a reopened part's worked example, Practice once every part passed, else `last_step` (as
 * in 004). Preview and learned concepts open at intro (placed ones resume like in-progress ones,
 * spec 012). */
function initialIndex(lesson: Lesson, step?: string | null): number {
  const { steps, kps } = lesson;
  // Staff preview may open at a step (`?step=kp:<slug>`, spec 011); unknown steps start at intro.
  if (lesson.preview) return step ? Math.max(0, steps.indexOf(step)) : 0;
  if (lesson.concept_status === "learned" && !lesson.placed) return 0;
  const practice = steps.indexOf("practice");
  if (practice >= 0 && lesson.practice.active) return practice;
  const active = kps.find((k) => k.active);
  if (active) return steps.indexOf(`kpq:${active.slug}`);
  if (lesson.waiting) return steps.indexOf(`kpq:${lesson.waiting.kp}`);
  const next = kps.find((k) => k.status !== "passed");
  if (next?.status === "failed") return steps.indexOf(`kp:${next.slug}`);
  if (!next && practice >= 0 && lesson.practice.status === "pending") return practice;
  const p = lesson.progress;
  if (!p) return 0;
  return Math.max(0, steps.indexOf(p.last_step));
}

type Ended =
  | { kind: "learned"; unlocked: ConceptRef[] | null }
  | { kind: "failed"; kp: LessonKp; remediations: RemediationRef[] };

function Passed() {
  return (
    <p className="flex items-center gap-2 rounded-md bg-[var(--success)]/10 px-3 py-3 font-medium">
      <CheckCircle2 className="size-5 text-[var(--success)]" aria-hidden />
      Passed ✓
    </p>
  );
}

/** The questions of one KP (rendered only on its `kpq` step, so it fetches only then). */
function KpPractice({
  course,
  lesson,
  kp,
  onDone,
  onGoToCheck,
}: {
  course: string;
  lesson: Lesson;
  kp: LessonKp;
  onDone: (result: AnswerResult) => void;
  onGoToCheck: () => void;
}) {
  const query = useKpQuestion(lesson.id, kp.slug);
  return (
    <PracticeRunner
      tutor
      header={`Practice · ${kp.title}`}
      query={query}
      submit={(body) => submitKpAnswer(lesson.id, kp.slug, body)}
      preview={lesson.preview}
      assetBase={lesson.asset_base}
      onDone={onDone}
      renderConflict={(code, error) => {
        if (code === "kp_passed") return <Passed />;
        if (code === "quiz_pending") return <QuizPendingPanel quizId={pendingQuizId(error)} />;
        if (code === "kp_waiting") {
          const body = (error instanceof ApiError ? error.body : undefined) as
            { remediations?: RemediationRef[] } | undefined;
          return (
            <WaitingPanel
              course={course}
              kpTitle={kp.title}
              remediations={body?.remediations ?? []}
              exclude={lesson.id}
            />
          );
        }
        if (code === "check_first") {
          return (
            <div className="space-y-3 rounded-lg border p-4">
              <p>Answer the quick check first.</p>
              <Button variant="outline" onClick={onGoToCheck}>
                Go to the check
              </Button>
            </div>
          );
        }
        return (
          <p className="rounded-lg border p-4">Pass the earlier parts of this lesson first.</p>
        );
      }}
    />
  );
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

function LessonView({
  course,
  lesson,
  startStep,
}: {
  course: string;
  lesson: Lesson;
  /** Staff preview only: open at this step (`?step=`). */
  startStep?: string | null;
}) {
  const queryClient = useQueryClient();
  const { steps, preview } = lesson;
  // Spec 012: a placed concept's KP steps are real sessions (not review), so a weak placement
  // surfaces on its own.
  const placed = !preview && lesson.concept_status === "learned" && !!lesson.placed;
  const review = !preview && lesson.concept_status === "learned" && !placed;
  const allOpen = preview || review;
  const [passed, setPassed] = useState<Set<string>>(
    () => new Set(lesson.kps.filter((k) => k.status === "passed").map((k) => k.slug)),
  );
  const [ended, setEnded] = useState<Ended | null>(null);
  const practicePassed = lesson.practice.status === "passed";

  const [index, setIndex] = useState(() => initialIndex(lesson, startStep));
  const [furthest, setFurthest] = useState(() =>
    Math.max(furthestSeen(lesson), initialIndex(lesson, startStep)),
  );
  const [result, setResult] = useState<CheckResult | null>(lesson.check_result);
  const submit = useSubmitCheck(lesson.id);
  const checkShownAt = useRef<number | null>(null);
  const lastPost = useRef<Promise<unknown>>(Promise.resolve());
  const topRef = useRef<HTMLDivElement>(null);

  const step = steps[index] ?? "intro";
  const checkIndex = steps.indexOf("check");
  const checkPending = checkIndex >= 0 && result === null;
  // A question step can't be passed over until its KP is passed.
  const firstUnpassed = steps.findIndex((s) => s.startsWith("kpq:") && !passed.has(s.slice(4)));
  const passedSteps = new Set([...passed].map((slug) => `kpq:${slug}`));
  if (practicePassed) passedSteps.add("practice");
  // Jump up to the furthest step reached + 1, but never past an unanswered check or an unpassed
  // question step.
  const maxIndex = allOpen
    ? steps.length - 1
    : Math.min(
        steps.length - 1,
        checkPending && furthest >= checkIndex ? furthest : furthest + 1,
        firstUnpassed >= 0 ? firstUnpassed : steps.length - 1,
      );
  const studentBlockedByCheck = !preview && checkPending && index >= checkIndex;
  const blockedByQuestions = !allOpen && step.startsWith("kpq:") && !passed.has(step.slice(4));
  const isLast = index === steps.length - 1;
  const finished = ended !== null;

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

  const refreshStatuses = () =>
    void lastPost.current.finally(() => queryClient.invalidateQueries({ queryKey: learnKeys.all }));

  const finish = () => {
    setEnded({ kind: "learned", unlocked: null });
    refreshStatuses();
  };

  const onPracticePassed = (unlocked: ConceptRef[] | null) => {
    setEnded({ kind: "learned", unlocked });
    refreshStatuses();
  };

  const onKpDone = (kp: LessonKp, r: AnswerResult) => {
    if (r.session_status === "failed") {
      setEnded({ kind: "failed", kp, remediations: r.remediations });
      refreshStatuses();
      return;
    }
    setPassed((prev) => new Set(prev).add(kp.slug));
    if (r.concept_learned) {
      setEnded({ kind: "learned", unlocked: r.unlocked });
      refreshStatuses();
      return;
    }
    const next = index + 1;
    if (next < steps.length) {
      setIndex(next);
      setFurthest((f) => Math.max(f, next));
    }
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

  if (ended) {
    return (
      <>
        <LessonHeader course={course} title={lesson.title} />
        {ended.kind === "learned" ? (
          <LearnedScreen
            course={course}
            title={lesson.title}
            unlocked={ended.unlocked}
            preview={preview}
          />
        ) : (
          <FailedScreen
            course={course}
            kpTitle={ended.kp.title}
            remediations={ended.remediations}
            exclude={lesson.id}
          />
        )}
      </>
    );
  }

  const kpIndex = steps.slice(0, index + 1).filter((s) => s.startsWith("kp:")).length;
  const kp = step.startsWith("kp:") ? lesson.kps.find((k) => `kp:${k.slug}` === step) : undefined;
  const kpq = step.startsWith("kpq:")
    ? lesson.kps.find((k) => `kpq:${k.slug}` === step)
    : undefined;
  const waitingHere = !preview && kpq !== undefined && lesson.waiting?.kp === kpq.slug;

  return (
    <div ref={topRef} className="scroll-mt-20">
      <LessonHeader course={course} title={lesson.title}>
        <StepIndicator
          steps={steps}
          current={index}
          maxIndex={maxIndex}
          passed={passedSteps}
          onJump={go}
        />
      </LessonHeader>
      {preview && (
        <p className="mx-auto mb-4 flex max-w-prose items-center gap-2 rounded-md bg-muted px-3 py-2 text-sm">
          <Eye className="size-4" aria-hidden />
          Teacher preview: nothing is saved
        </p>
      )}
      {review && (
        <p className="mx-auto mb-4 max-w-prose text-sm text-muted-foreground">
          You&apos;ve learned this concept. Every step is open for review.
        </p>
      )}
      {placed && (
        <p className="mx-auto mb-4 max-w-prose text-sm text-muted-foreground">
          You placed out of this concept. Working through the steps is optional, and still earns XP
          the first time.
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
        {kpq &&
          (!preview && (review || passed.has(kpq.slug)) ? (
            <div className="space-y-4">
              <p className="text-sm font-semibold text-muted-foreground">Practice · {kpq.title}</p>
              <Passed />
            </div>
          ) : waitingHere ? (
            <WaitingPanel
              course={course}
              kpTitle={kpq.title}
              remediations={lesson.waiting?.remediations ?? []}
              exclude={lesson.id}
            />
          ) : (
            <KpPractice
              key={kpq.slug}
              course={course}
              lesson={lesson}
              kp={kpq}
              onDone={(r) => onKpDone(kpq, r)}
              onGoToCheck={() => go(checkIndex)}
            />
          ))}
        {step === "practice" && (
          <PracticeStep
            lesson={lesson}
            passed={review || practicePassed}
            onPassed={onPracticePassed}
          />
        )}
      </article>
      <div className="sticky bottom-0 -mx-4 mt-6 border-t bg-background/95 px-4 py-3 backdrop-blur sm:static sm:mx-0 sm:bg-transparent sm:px-0 sm:backdrop-blur-none">
        <div className="mx-auto flex max-w-prose items-center justify-between gap-3">
          <Button variant="outline" onClick={() => go(index - 1)} disabled={index === 0}>
            Back
          </Button>
          {isLast ? (
            // With a Practice step, passing it finishes the lesson (spec 006).
            (step !== "practice" || preview || review) && (
              <Button onClick={finish} disabled={studentBlockedByCheck || blockedByQuestions}>
                Finish lesson
              </Button>
            )
          ) : (
            <Button
              onClick={() => go(index + 1)}
              disabled={(studentBlockedByCheck && index === checkIndex) || blockedByQuestions}
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
  const [params] = useSearchParams();
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
          <LessonHeader course={course} title="Learn these first" />
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
  return (
    <LessonView key={ref} course={course} lesson={lesson.data} startStep={params.get("step")} />
  );
}
