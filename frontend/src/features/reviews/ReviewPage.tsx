import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CalendarCheck, CheckCircle2, RotateCcw } from "lucide-react";
import { type ReactNode, useCallback, useState } from "react";
import { Link, useParams } from "react-router";

import { Button } from "@/components/ui/button";
import { learnKeys, postProgress } from "@/features/learn/api";
import { conceptCourse, lessonPath } from "@/features/learn/paths";
import { PracticeRunner } from "@/features/learn/PracticeRunner";
import { useStepTimer } from "@/features/learn/useStepTimer";
import {
  reviewKeys,
  submitReviewAnswer,
  useReviewQuestion,
  useReviewQueue,
} from "@/features/reviews/api";
import { quizKeys } from "@/features/quiz/api";
import { shortDate } from "@/lib/dates";
import type { AnswerResult } from "@/lib/types";

const STEP = "review"; // study time is logged against the concept as practice

function Outcome({
  conceptId,
  title,
  result,
}: {
  conceptId: string;
  title: string;
  result: AnswerResult;
}) {
  const review = result.review;
  if (review?.relearn) {
    return (
      <End icon={<RotateCcw className="size-10 text-[var(--warning)]" aria-hidden />}>
        <h2 className="text-2xl font-semibold">Let&apos;s relearn {title}</h2>
        <Button asChild className="w-full sm:w-auto">
          <Link to={lessonPath(conceptCourse(conceptId), conceptId)}>Go to the lesson</Link>
        </Button>
      </End>
    );
  }
  if (result.session_status === "passed") {
    return (
      <End icon={<CheckCircle2 className="size-10 text-[var(--success)]" aria-hidden />}>
        <h2 className="text-2xl font-semibold">
          {review?.next_due ? `Nice, see you again on ${shortDate(review.next_due)}` : "Nice work"}
        </h2>
      </End>
    );
  }
  return (
    <End icon={<CalendarCheck className="size-10 text-[var(--warning)]" aria-hidden />}>
      <h2 className="text-2xl font-semibold">We&apos;ll review this again tomorrow</h2>
    </End>
  );
}

function End({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-4 py-8 text-center">
      {icon}
      {children}
      <Button asChild variant="outline" className="w-full sm:w-auto">
        <Link to="/">Home</Link>
      </Button>
    </div>
  );
}

function NotOffered({ code }: { code: string }) {
  return (
    <div className="space-y-3 rounded-lg border p-4">
      <p>
        {code === "review_cap"
          ? "That's today's reviews done. More tomorrow."
          : "This review isn't due today."}
      </p>
      <Button asChild variant="outline">
        <Link to="/">Back home</Link>
      </Button>
    </div>
  );
}

/** `/review/:course/:concept`: one scheduled review of a learned concept (spec 007). */
export function ReviewPage() {
  const { course = "", concept = "" } = useParams();
  const conceptId = `${course}/${concept}`;
  const queryClient = useQueryClient();
  const [done, setDone] = useState<AnswerResult | null>(null);
  const query = useReviewQuestion(conceptId);
  // The title comes from Today's reviews (kept once known: the list changes when this ends).
  const queue = useReviewQueue();
  const found = queue.data?.offered.find((o) => o.concept.id === conceptId)?.concept.title;
  const [title, setTitle] = useState<string | null>(null);
  if (found && found !== title) setTitle(found);
  const name = found ?? title ?? concept.replaceAll("-", " ");
  const report = useCallback(
    (step: string, seconds: number, opts: { keepalive: boolean }) =>
      void postProgress(conceptId, step, seconds, opts),
    [conceptId],
  );
  useStepTimer(done || query.isError ? null : STEP, report);

  return (
    <div className="mx-auto max-w-prose">
      <Button asChild variant="ghost" size="sm" className="mb-2 -ml-2">
        <Link to="/">
          <ArrowLeft aria-hidden />
          Home
        </Link>
      </Button>
      <header className="mb-6 space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Review: {name}</h1>
        <p className="text-muted-foreground">3 to 5 questions on something you&apos;ve learned</p>
      </header>
      {done ? (
        <Outcome conceptId={conceptId} title={name} result={done} />
      ) : (
        <PracticeRunner
          header={query.data ? `Question ${query.data.position} of 3–5` : "Review"}
          query={query}
          submit={(body) => submitReviewAnswer(conceptId, body)}
          passedLabel="Review passed ✓"
          onDone={(r) => {
            setDone(r);
            void queryClient.invalidateQueries({ queryKey: reviewKeys.all });
            void queryClient.invalidateQueries({ queryKey: learnKeys.all });
            void queryClient.invalidateQueries({ queryKey: quizKeys.current });
          }}
          renderConflict={(code) => <NotOffered code={code} />}
        />
      )}
    </div>
  );
}
