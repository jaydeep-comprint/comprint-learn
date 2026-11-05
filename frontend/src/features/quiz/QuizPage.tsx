import { useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Check, ClipboardCheck, Loader2 } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";

import { Markdown } from "@/components/markdown/Markdown";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { AnswerForm } from "@/features/learn/AnswerForm";
import { type AnswerFields, conflictCode, learnKeys } from "@/features/learn/api";
import {
  quizKeys,
  startQuiz,
  submitQuizAnswer,
  useQuizQuestion,
  useQuizResult,
  useQuizState,
} from "@/features/quiz/api";
import { QuizResultView } from "@/features/quiz/QuizResult";
import { QuizTimer } from "@/features/quiz/QuizTimer";
import { reviewKeys } from "@/features/reviews/api";
import { xpKeys } from "@/features/xp/api";
import { ApiError } from "@/lib/api";
import type { QuizState } from "@/lib/types";
import { NotFoundPage } from "@/pages/NotFoundPage";

function Loading() {
  return (
    <div className="space-y-3 py-6" aria-busy="true">
      <Skeleton className="h-8 w-2/3" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-10 w-48" />
    </div>
  );
}

function Retry({ text, onRetry }: { text: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 py-8 text-center">
      <AlertCircle className="size-8 text-muted-foreground" aria-hidden />
      <p>{text}</p>
      <Button variant="outline" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}

function Intro({ quiz, onStart }: { quiz: QuizState; onStart: () => Promise<void> }) {
  const [starting, setStarting] = useState(false);
  return (
    <div className="space-y-6 py-6">
      <Button asChild variant="ghost" size="sm" className="-ml-2">
        <Link to="/">
          <ArrowLeft aria-hidden />
          Home
        </Link>
      </Button>
      <div className="space-y-2">
        <ClipboardCheck className="size-10 text-warning" aria-hidden />
        <h1 className="text-2xl font-semibold tracking-tight">Quiz time!</h1>
        <p className="text-lg">
          {quiz.total} questions · {quiz.minutes} minutes · no notes
        </p>
      </div>
      <ul className="list-disc space-y-1 pl-5">
        <li>It mixes everything you&apos;ve learned. Work from memory.</li>
        <li>One question at a time, with no going back.</li>
        <li>You&apos;ll see how you did at the end. Misses come back as reviews.</li>
        <li>Once you start, the timer keeps running, even if you leave.</li>
      </ul>
      <Button
        className="w-full sm:w-auto"
        disabled={starting}
        onClick={async () => {
          setStarting(true);
          try {
            await onStart();
          } catch {
            toast.error("Couldn't start the quiz, try again");
          } finally {
            setStarting(false);
          }
        }}
      >
        {starting && <Loader2 className="animate-spin" aria-hidden />}
        Start
      </Button>
    </div>
  );
}

function Active({ quiz, onOver }: { quiz: QuizState; onOver: () => void }) {
  const query = useQuizQuestion(quiz.id, true);
  const [submitting, setSubmitting] = useState(false);
  const [savedPosition, setSavedPosition] = useState<number | null>(null);
  const shownAt = useRef(0);
  const promptId = useId();
  const question = query.data;
  const overCode = conflictCode(query.error);

  useEffect(() => {
    shownAt.current = performance.now();
  }, [question?.position]);
  useEffect(() => {
    if (overCode === "quiz_over") onOver();
  }, [overCode, onOver]);

  const onSubmit = async (fields: AnswerFields) => {
    if (!question) return;
    setSubmitting(true);
    try {
      const saved = await submitQuizAnswer(quiz.id, {
        ...fields,
        position: question.position,
        session_id: question.session_id ?? undefined,
        time_taken_ms: Math.round(performance.now() - shownAt.current),
      });
      setSavedPosition(question.position);
      if (saved.finished) onOver();
      else await query.refetch();
    } catch (error) {
      const code = conflictCode(error);
      if (code === "quiz_over") onOver();
      else if (code === "stale_question") await query.refetch();
      else toast.error("Couldn't save, try again");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-5">
      {quiz.seconds_left !== null && (
        <QuizTimer secondsLeft={quiz.seconds_left} onExpire={onOver} />
      )}
      {query.isError && overCode !== "quiz_over" ? (
        <Retry text="Couldn't load this question." onRetry={() => query.refetch()} />
      ) : !question || query.isFetching ? (
        <Loading />
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold tracking-wide text-muted-foreground">
              Question {question.position} of {quiz.total}
            </p>
            <p role="status" className="flex items-center gap-1 text-sm text-muted-foreground">
              {savedPosition !== null && (
                <>
                  <Check className="size-4 text-[var(--success)]" aria-hidden />
                  Saved
                </>
              )}
            </p>
          </div>
          <div id={promptId}>
            <Markdown>{question.prompt_md}</Markdown>
          </div>
          <AnswerForm
            key={`${question.item_id}-${question.position}`}
            name={`quiz-${question.position}`}
            part={{
              type:
                question.type === "numeric" || question.type === "mcq"
                  ? question.type
                  : "expression",
              unit: question.unit,
              unitRequired: !!question.unit_required,
              options: question.options,
              variables: question.variables,
            }}
            marked={null}
            submitting={submitting}
            labelledBy={promptId}
            onSubmit={onSubmit}
          />
        </div>
      )}
    </div>
  );
}

function Result({ quizId }: { quizId: string }) {
  const query = useQuizResult(quizId, true);
  const notYet = conflictCode(query.error) === "quiz_not_finished";
  useEffect(() => {
    // The browser's timer can run out a moment before the server's: ask again shortly.
    if (!notYet) return;
    const handle = window.setTimeout(() => void query.refetch(), 3000);
    return () => window.clearTimeout(handle);
  }, [notYet, query]);
  if (query.isPending || notYet) return <Loading />;
  if (query.isError) {
    return <Retry text="Couldn't load your result." onRetry={() => query.refetch()} />;
  }
  return <QuizResultView quizId={quizId} result={query.data} />;
}

/** `/quiz/:id`: the timed mixed quiz, without the app navigation (spec 007). */
export function QuizPage() {
  const { id = "" } = useParams();
  const state = useQuizState(id);
  const queryClient = useQueryClient();
  const [over, setOver] = useState(false);

  const onOver = useCallback(() => {
    setOver(true);
    for (const key of [quizKeys.current, reviewKeys.all, learnKeys.all, xpKeys.me]) {
      void queryClient.invalidateQueries({ queryKey: key });
    }
  }, [queryClient]);

  let body;
  if (state.isPending) {
    body = <Loading />;
  } else if (state.isError) {
    if (state.error instanceof ApiError && [403, 404].includes(state.error.status)) {
      return <NotFoundPage />;
    }
    body = <Retry text="Couldn't load this quiz." onRetry={() => state.refetch()} />;
  } else {
    const quiz = state.data;
    if (over || quiz.status === "finished") {
      body = <Result quizId={quiz.id} />;
    } else if (quiz.status === "cancelled") {
      body = (
        <div className="space-y-4 py-8 text-center">
          <p>This quiz was called off: there&apos;s nothing learned to quiz you on right now.</p>
          <Button asChild variant="outline">
            <Link to="/">Back to learning</Link>
          </Button>
        </div>
      );
    } else if (quiz.status === "pending") {
      body = (
        <Intro
          quiz={quiz}
          onStart={async () => {
            const started = await startQuiz(quiz.id);
            queryClient.setQueryData(quizKeys.state(quiz.id), started);
            void queryClient.invalidateQueries({ queryKey: quizKeys.current });
          }}
        />
      );
    } else {
      body = <Active quiz={quiz} onOver={onOver} />;
    }
  }
  return <main className="mx-auto min-h-svh max-w-prose px-4 pb-10">{body}</main>;
}
