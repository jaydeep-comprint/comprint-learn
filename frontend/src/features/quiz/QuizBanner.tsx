import { ClipboardCheck } from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { formatClock, quizPath, useCurrentQuiz } from "@/features/quiz/api";

/** Home: "Quiz time!" while a quiz is pending or active (spec 007). Renders nothing otherwise. */
export function QuizBanner() {
  const query = useCurrentQuiz();
  const quiz = query.data;
  if (!quiz) return null;
  const active = quiz.status === "active";
  return (
    <section
      aria-labelledby="quiz-banner"
      className="space-y-3 rounded-xl border border-warning/50 bg-warning/10 p-4 sm:p-5"
    >
      <div className="flex items-start gap-3">
        <ClipboardCheck className="mt-0.5 size-6 shrink-0 text-warning" aria-hidden />
        <div className="space-y-1">
          <h2 id="quiz-banner" className="text-lg font-semibold">
            Quiz time!
          </h2>
          <p>
            {quiz.total} questions · {quiz.minutes} minutes · no notes
          </p>
          <p className="text-sm text-muted-foreground">New lessons are paused until you take it.</p>
        </div>
      </div>
      <Button asChild className="w-full sm:w-auto">
        <Link to={quizPath(quiz.id)}>
          {active && quiz.seconds_left !== null
            ? `Resume quiz · ${formatClock(quiz.seconds_left)} left`
            : "Start quiz"}
        </Link>
      </Button>
    </section>
  );
}
