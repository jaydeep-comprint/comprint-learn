import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, RotateCcw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { learnKeys, submitPracticeAnswer, usePracticeQuestion } from "@/features/learn/api";
import { PracticeRunner } from "@/features/learn/PracticeRunner";
import { pendingQuizId } from "@/features/quiz/api";
import { QuizPendingPanel } from "@/features/quiz/QuizPendingPanel";
import type { AnswerResult, ConceptRef, Lesson } from "@/lib/types";

const HEADER = "Practice · Put it together";

function continueLabel(result: AnswerResult): string {
  if (result.session_status !== "failed") return "Continue";
  return result.tests ? "Fix your code and submit again" : "Try again";
}

/** One attempt at the lesson's Practice step (a fresh one after each fail). */
function Attempt({
  lesson,
  again,
  onPassed,
}: {
  lesson: Lesson;
  again: boolean;
  onPassed: (unlocked: ConceptRef[] | null) => void;
}) {
  const query = usePracticeQuestion(lesson.id, again);
  const queryClient = useQueryClient();
  const [attempt, setAttempt] = useState(0);
  return (
    <PracticeRunner
      tutor
      key={attempt}
      header={HEADER}
      query={query}
      submit={(body) => submitPracticeAnswer(lesson.id, body, again)}
      preview={lesson.preview || again}
      assetBase={lesson.asset_base}
      passedLabel="Practice passed ✓"
      continueLabel={continueLabel}
      onDone={async (r) => {
        if (r.session_status === "passed") {
          if (r.concept_learned || lesson.preview || again) {
            onPassed(r.concept_learned ? r.unlocked : null);
            return;
          }
          // Passed, but a part was added since: the concept isn't learned yet.
          toast.info("Practice passed. Finish the remaining part to learn this concept.");
          void queryClient.invalidateQueries({ queryKey: learnKeys.all });
          return;
        }
        // Try again: a new attempt starts now (a code task keeps the student's code).
        await query.refetch();
        setAttempt((a) => a + 1);
      }}
      renderConflict={(code, error) =>
        code === "practice_passed" ? (
          <PassedPanel />
        ) : code === "quiz_pending" ? (
          <QuizPendingPanel quizId={pendingQuizId(error)} />
        ) : (
          <p className="rounded-lg border p-4">
            Pass every part of this lesson first, then practise.
          </p>
        )
      }
    />
  );
}

function PassedPanel({ onAgain }: { onAgain?: () => void }) {
  return (
    <div className="space-y-3">
      <p className="flex items-center gap-2 rounded-md bg-[var(--success)]/10 px-3 py-3 font-medium">
        <CheckCircle2 className="size-5 text-[var(--success)]" aria-hidden />
        Passed ✓
      </p>
      {onAgain && (
        <Button variant="outline" onClick={onAgain}>
          <RotateCcw aria-hidden /> Practise again
        </Button>
      )}
    </div>
  );
}

/** The lesson's required Practice step (spec 006): one multi-step problem or Python task per
 * attempt. Passing it makes the concept learned. A learned concept shows "Passed ✓" and
 * "Practise again", an unscored attempt that writes nothing. */
export function PracticeStep({
  lesson,
  passed,
  onPassed,
}: {
  lesson: Lesson;
  passed: boolean;
  onPassed: (unlocked: ConceptRef[] | null) => void;
}) {
  const [again, setAgain] = useState(false);
  if (!lesson.preview && passed && !again) {
    return (
      <div className="space-y-4">
        <p className="text-sm font-semibold text-muted-foreground">{HEADER}</p>
        <PassedPanel onAgain={() => setAgain(true)} />
      </div>
    );
  }
  const practiceOnly = !lesson.preview && again;
  return (
    <div className="space-y-3">
      {practiceOnly && (
        <p className="w-fit rounded-md border px-2 py-0.5 text-xs text-muted-foreground">
          Practice only, no XP
        </p>
      )}
      <Attempt lesson={lesson} again={practiceOnly} onPassed={onPassed} />
    </div>
  );
}
