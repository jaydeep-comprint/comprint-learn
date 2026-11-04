import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Markdown } from "@/components/markdown/Markdown";
import { Button } from "@/components/ui/button";
import type { CheckResult, Lesson } from "@/lib/types";
import { cn } from "@/lib/utils";

type Check = NonNullable<Lesson["check"]>;

/** The one-try misconception check. Graded on the server; the result arrives after a submit. */
export function CheckStep({
  check,
  result,
  assetBase,
  submitting,
  onSubmit,
}: {
  check: Check;
  result: CheckResult | null;
  assetBase: string;
  submitting: boolean;
  onSubmit: (optionId: string) => void;
}) {
  const [picked, setPicked] = useState<string | null>(result?.chosen ?? null);
  const resultRef = useRef<HTMLDivElement>(null);
  const answered = result !== null;
  const shown = answered ? result.chosen : picked;

  // Focus the result right after a submit (not when revisiting an answered check).
  const wasAnswered = useRef(answered);
  useEffect(() => {
    if (answered && !wasAnswered.current) resultRef.current?.focus();
    wasAnswered.current = answered;
  }, [answered]);

  return (
    <div className="space-y-5">
      <p className="text-sm font-semibold tracking-wide text-muted-foreground uppercase">
        Quick check
      </p>
      <div id="check-prompt">
        <Markdown assetBase={assetBase}>{check.prompt}</Markdown>
      </div>
      <div role="radiogroup" aria-labelledby="check-prompt" className="space-y-2">
        {check.options.map((o) => {
          const isChosen = shown === o.id;
          const isCorrect = answered && result.correct_option === o.id;
          const isWrongPick = answered && isChosen && !result.correct;
          return (
            <label
              key={o.id}
              className={cn(
                "flex min-h-11 cursor-pointer items-start gap-3 rounded-lg border-2 p-3 transition-colors",
                !answered && isChosen && "border-primary bg-muted",
                !answered && !isChosen && "hover:bg-muted/50",
                isCorrect && "border-[var(--success)] bg-[var(--success)]/10",
                isWrongPick && "border-destructive bg-destructive/10",
                answered && "cursor-default",
              )}
            >
              <input
                type="radio"
                name="check-option"
                value={o.id}
                checked={isChosen}
                disabled={answered || submitting}
                onChange={() => setPicked(o.id)}
                className="mt-1 size-4 accent-primary"
              />
              <span className="min-w-0 flex-1">
                <Markdown assetBase={assetBase}>{o.text}</Markdown>
                {isCorrect && (
                  <span className="mt-1 block text-sm font-medium text-[var(--success)]">
                    Correct answer
                  </span>
                )}
              </span>
            </label>
          );
        })}
      </div>
      {!answered && (
        <Button
          onClick={() => picked && onSubmit(picked)}
          disabled={!picked || submitting}
          className="w-full sm:w-auto"
        >
          {submitting && <Loader2 className="animate-spin" aria-hidden />}
          Submit
        </Button>
      )}
      {answered && (
        <div
          ref={resultRef}
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
          {result.misconception && (
            <p className="font-medium">Common mix-up: {result.misconception.title}</p>
          )}
          {result.explanation_md && (
            <Markdown assetBase={assetBase}>{result.explanation_md}</Markdown>
          )}
        </div>
      )}
    </div>
  );
}
