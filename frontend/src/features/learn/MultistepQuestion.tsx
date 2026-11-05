import { CheckCircle2, XCircle } from "lucide-react";
import { useId } from "react";

import { Markdown } from "@/components/markdown/Markdown";
import type { AnswerFields } from "@/features/learn/api";
import { AnswerForm } from "@/features/learn/AnswerForm";
import { multistepPassed } from "@/features/learn/multistep";
import type { AnswerResult, Question, StepPublic } from "@/lib/types";

function stepAnswer(step: StepPublic, display: string): string {
  if (step.type === "mcq") return step.options?.find((o) => o.id === display)?.text ?? display;
  if (step.type === "expression") return `$${display}$`;
  return display;
}

/** A multi-step problem, one step at a time: the steps answered so far (with the right value for
 * these numbers), then the current step; after the last one, the summary. The stem is shown above
 * (`QuestionStep`). One try per step; the problem continues with the correct values. */
export function MultistepQuestion({
  question,
  result,
  submitting,
  assetBase,
  onSubmit,
  onDraftChange,
}: {
  question: Question;
  result: AnswerResult | null;
  submitting: boolean;
  assetBase?: string;
  onSubmit: (fields: AnswerFields) => void;
  /** The current step's draft, for the AI tutor (spec 009). */
  onDraftChange?: (draft: string | null) => void;
}) {
  const id = useId();
  const steps = question.steps ?? [];
  const done = result?.step_results ?? question.step_results ?? [];
  const finished = done.length >= steps.length;
  const current = Math.min(done.length, steps.length - 1);
  const step = steps[current];
  const passed = result?.item_correct ?? multistepPassed(done, steps.length);
  const right = done.filter((r) => r.correct).length;

  return (
    <div className="space-y-4">
      {done.length > 0 && (
        <ol className="space-y-2" aria-label="Steps answered" data-testid="steps-done">
          {done.map((r, i) => {
            const s = steps[i];
            if (!s) return null;
            const answer = stepAnswer(s, r.display_answer);
            return (
              <li key={i} className="rounded-md border px-3 py-2 text-sm">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  {r.correct ? (
                    <CheckCircle2
                      className="size-4 self-center text-[var(--success)]"
                      aria-label="Correct"
                    />
                  ) : (
                    <XCircle
                      className="size-4 self-center text-destructive"
                      aria-label="Not quite"
                    />
                  )}
                  <span className="font-medium">Step {i + 1}</span>
                  {r.correct ? (
                    <Markdown assetBase={assetBase}>{answer}</Markdown>
                  ) : (
                    <>
                      <span>Answer:</span>
                      <Markdown assetBase={assetBase}>{answer}</Markdown>
                    </>
                  )}
                </div>
                {r.note && <p className="text-xs">{r.note}</p>}
                {r.misconception && (
                  <p className="text-xs font-medium">Common mix-up: {r.misconception.title}</p>
                )}
              </li>
            );
          })}
        </ol>
      )}
      {!finished && step && (
        <div className="space-y-3 rounded-lg border-2 border-primary/40 p-4">
          <p className="text-sm font-semibold text-muted-foreground">
            Step {current + 1} of {steps.length}
          </p>
          <div id={`${id}-prompt`}>
            <Markdown assetBase={assetBase}>{step.prompt_md}</Markdown>
          </div>
          <AnswerForm
            key={`${question.item_id}-${question.position}-${current}`}
            name={`q-${question.item_id}-${question.position}-${current}`}
            part={{
              type: step.type,
              unit: step.unit,
              unitRequired: step.type === "numeric" && !!step.unit,
              options: step.options,
              variables: step.variables,
            }}
            marked={null}
            submitting={submitting}
            labelledBy={`${id}-prompt`}
            onSubmit={(fields) => onSubmit({ ...fields, step: current })}
            onDraftChange={onDraftChange}
          />
        </div>
      )}
      {finished && (
        <div role="status" className="space-y-2 rounded-lg border p-4">
          <p className="flex items-center gap-2 font-semibold">
            {passed ? (
              <CheckCircle2 className="size-5 text-[var(--success)]" aria-hidden />
            ) : (
              <XCircle className="size-5 text-destructive" aria-hidden />
            )}
            {passed ? "Problem solved ✓" : `Not quite: ${right} of ${steps.length} steps`}
          </p>
          {result?.explanation_md && (
            <Markdown assetBase={assetBase}>{result.explanation_md}</Markdown>
          )}
        </div>
      )}
    </div>
  );
}
