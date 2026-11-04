import { CheckCircle2, Loader2 } from "lucide-react";
import { useId, useState } from "react";

import { Markdown } from "@/components/markdown/Markdown";
import { Button } from "@/components/ui/button";
import { ExpressionInput } from "@/features/learn/ExpressionInput";
import { NumericInput } from "@/features/learn/NumericInput";
import { ResultPanel } from "@/features/learn/ResultPanel";
import type { AnswerResult, Question } from "@/lib/types";
import { cn } from "@/lib/utils";

/** This session's answers: green/red dots, the current question hollow. */
function Dots({ results, pending }: { results: boolean[]; pending: boolean }) {
  const right = results.filter(Boolean).length;
  return (
    <div
      className="flex items-center gap-1.5"
      role="img"
      aria-label={`${right} of ${results.length} correct so far`}
    >
      {results.map((ok, i) => (
        <span
          key={i}
          className={cn("size-3 rounded-full", ok ? "bg-[var(--success)]" : "bg-destructive")}
          data-testid={ok ? "dot-correct" : "dot-wrong"}
        />
      ))}
      {pending && (
        <span
          className="size-3 rounded-full border-2 border-muted-foreground"
          data-testid="dot-current"
        />
      )}
    </div>
  );
}

function McqOptions({
  question,
  picked,
  result,
  disabled,
  onPick,
  labelledBy,
}: {
  question: Question;
  picked: string;
  result: AnswerResult | null;
  disabled: boolean;
  onPick: (id: string) => void;
  labelledBy: string;
}) {
  return (
    <div role="radiogroup" aria-labelledby={labelledBy} className="space-y-2">
      {(question.options ?? []).map((o) => {
        const isChosen = picked === o.id;
        const isCorrect = result !== null && result.display_answer === o.id;
        const isWrongPick = result !== null && isChosen && !result.correct;
        return (
          <label
            key={o.id}
            className={cn(
              "flex min-h-11 cursor-pointer items-start gap-3 rounded-lg border-2 p-3 transition-colors",
              !result && isChosen && "border-primary bg-muted",
              !result && !isChosen && "hover:bg-muted/50",
              isCorrect && "border-[var(--success)] bg-[var(--success)]/10",
              isWrongPick && "border-destructive bg-destructive/10",
              result && "cursor-default",
            )}
          >
            <input
              type="radio"
              name={`q-${question.item_id}-${question.position}`}
              value={o.id}
              checked={isChosen}
              disabled={disabled}
              onChange={() => onPick(o.id)}
              className="mt-1 size-4 accent-primary"
            />
            <span className="min-w-0 flex-1">
              <Markdown>{o.text}</Markdown>
            </span>
          </label>
        );
      })}
    </div>
  );
}

/** One question: prompt, input, submit; then the result and what comes next.
 *
 * Remount it (`key`) for each new question so the input starts empty. `preview` (staff) shows
 * "Another question" instead of dots and pass/fail. */
export function QuestionStep({
  header,
  question,
  result,
  submitting,
  preview = false,
  assetBase,
  onSubmit,
  onNext,
  onContinue,
}: {
  header: string;
  question: Question;
  result: AnswerResult | null;
  submitting: boolean;
  preview?: boolean;
  assetBase?: string;
  onSubmit: (response: string) => void;
  /** Next question (active session) or, for staff, another question. */
  onNext: () => void;
  /** After the session passed or failed. */
  onContinue: () => void;
}) {
  const id = useId();
  const promptId = `${id}-prompt`;
  const inputId = `${id}-input`;
  const [value, setValue] = useState("");
  const answered = result !== null;
  const status = result?.session_status ?? "active";
  const results = result?.results ?? question.results;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold tracking-wide text-muted-foreground">{header}</p>
        {!preview && <Dots results={results} pending={!answered} />}
      </div>
      <div id={promptId}>
        <Markdown assetBase={assetBase}>{question.prompt_md}</Markdown>
      </div>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (value.trim() && !answered && !submitting) onSubmit(value.trim());
        }}
      >
        {question.type === "mcq" ? (
          <McqOptions
            question={question}
            picked={value}
            result={result}
            disabled={answered || submitting}
            onPick={setValue}
            labelledBy={promptId}
          />
        ) : (
          <div className="space-y-1">
            <label htmlFor={inputId} className="text-sm font-medium">
              Your answer
            </label>
            {question.type === "numeric" ? (
              <NumericInput
                id={inputId}
                value={value}
                unit={question.unit}
                disabled={answered || submitting}
                onChange={setValue}
              />
            ) : (
              <ExpressionInput
                id={inputId}
                value={value}
                variables={question.variables}
                disabled={answered || submitting}
                onChange={setValue}
              />
            )}
          </div>
        )}
        {!answered && (
          <Button type="submit" disabled={!value.trim() || submitting} className="w-full sm:w-auto">
            {submitting && <Loader2 className="animate-spin" aria-hidden />}
            Submit
          </Button>
        )}
      </form>
      {result && (
        <>
          <ResultPanel question={question} result={result} assetBase={assetBase} />
          {preview ? (
            <Button onClick={onNext} className="w-full sm:w-auto">
              Another question
            </Button>
          ) : status === "active" ? (
            <Button onClick={onNext} className="w-full sm:w-auto">
              Next question
            </Button>
          ) : (
            <div className="space-y-3">
              {status === "passed" && (
                <p className="flex items-center gap-2 rounded-md bg-[var(--success)]/10 px-3 py-2 font-medium">
                  <CheckCircle2 className="size-5 text-[var(--success)]" aria-hidden />
                  Part passed ✓
                </p>
              )}
              <Button onClick={onContinue} className="w-full sm:w-auto">
                Continue
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
