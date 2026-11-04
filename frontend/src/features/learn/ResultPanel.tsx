import { CheckCircle2, XCircle } from "lucide-react";
import { useEffect, useRef } from "react";

import { Markdown } from "@/components/markdown/Markdown";
import type { AnswerResult, Question } from "@/lib/types";

function answerText(question: Question, result: AnswerResult): string {
  if (question.type === "mcq") {
    const option = question.options?.find((o) => o.id === result.display_answer);
    return option?.text ?? result.display_answer;
  }
  if (question.type === "expression") return `$${result.display_answer}$`;
  return result.display_answer;
}

/** "Correct!" / "Not quite", any note, the answer for these numbers, a tagged misconception and
 * the explanation. Takes focus when it appears. */
export function ResultPanel({
  question,
  result,
  assetBase,
}: {
  question: Question;
  result: AnswerResult;
  assetBase?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => ref.current?.focus(), []);
  return (
    <div
      ref={ref}
      tabIndex={-1}
      role="status"
      className="space-y-2 rounded-lg border p-4 outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <p className="flex items-center gap-2 font-semibold">
        {result.correct ? (
          <CheckCircle2 className="size-5 text-[var(--success)]" aria-hidden />
        ) : (
          <XCircle className="size-5 text-destructive" aria-hidden />
        )}
        {result.correct ? "Correct!" : "Not quite"}
      </p>
      {result.note && <p className="text-sm">{result.note}</p>}
      <div className="flex flex-wrap items-baseline gap-1">
        <span className="font-medium">Answer:</span>
        <Markdown assetBase={assetBase}>{answerText(question, result)}</Markdown>
      </div>
      {result.misconception && (
        <p className="font-medium">Common mix-up: {result.misconception.title}</p>
      )}
      {result.explanation_md && <Markdown assetBase={assetBase}>{result.explanation_md}</Markdown>}
    </div>
  );
}
