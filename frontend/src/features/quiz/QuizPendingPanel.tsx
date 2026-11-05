import { ClipboardCheck } from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { quizPath } from "@/features/quiz/api";

/** Shown in place of a question that would open a new KP or practice session (spec 007). */
export function QuizPendingPanel({ quizId }: { quizId: string | null }) {
  return (
    <div className="space-y-3 rounded-lg border border-warning/50 bg-warning/10 p-4">
      <p className="flex items-center gap-2 font-medium">
        <ClipboardCheck className="size-5 text-warning" aria-hidden />
        Take your quiz to keep learning
      </p>
      <p className="text-sm text-muted-foreground">
        It mixes everything you&apos;ve learned. Your misses come back as reviews.
      </p>
      <Button asChild className="w-full sm:w-auto">
        <Link to={quizId ? quizPath(quizId) : "/"}>{quizId ? "Go to the quiz" : "Home"}</Link>
      </Button>
    </div>
  );
}
