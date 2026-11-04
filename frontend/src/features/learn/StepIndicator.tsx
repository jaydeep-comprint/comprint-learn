import { cn } from "@/lib/utils";

function kpNumber(index: number, steps: string[]): number {
  return steps.slice(0, index + 1).filter((s) => s.startsWith("kp:")).length;
}

function stepLabel(step: string, index: number, steps: string[]): string {
  if (step === "intro") return "Intro";
  if (step === "check") return "Check";
  if (step === "practice") return "Practice";
  const n = kpNumber(index, steps);
  return step.startsWith("kpq:") ? `${n}✎` : String(n);
}

function stepName(step: string, index: number, steps: string[], passed: boolean): string {
  if (step === "intro") return "Introduction";
  if (step === "check") return "Quick check";
  if (step === "practice") return `Practice${passed ? " (passed)" : ""}`;
  const n = kpNumber(index, steps);
  if (step.startsWith("kpq:")) return `Practice ${n}${passed ? " (passed)" : ""}`;
  return `Worked example ${n}`;
}

/** Labelled dots (Intro · Check · 1 · 1✎ · 2 · 2✎ …); "Step k of n" on phones. Steps past
 * `maxIndex` are disabled; passed question steps get a ✓. */
export function StepIndicator({
  steps,
  current,
  maxIndex,
  passed = new Set<string>(),
  onJump,
}: {
  steps: string[];
  current: number;
  maxIndex: number;
  /** `kpq:<slug>` steps whose KP is passed. */
  passed?: ReadonlySet<string>;
  onJump: (index: number) => void;
}) {
  return (
    <nav aria-label="Lesson steps" className="flex items-center gap-3">
      <ol className="flex flex-wrap items-center gap-1 sm:gap-2">
        {steps.map((step, i) => {
          const active = i === current;
          const done = passed.has(step);
          return (
            <li key={step}>
              <button
                type="button"
                aria-current={active ? "step" : undefined}
                aria-label={stepName(step, i, steps, done)}
                disabled={i > maxIndex}
                onClick={() => onJump(i)}
                className={cn(
                  "flex min-h-8 min-w-8 items-center justify-center gap-1 rounded-full px-1.5 text-xs font-medium transition-colors sm:px-2.5",
                  "disabled:cursor-not-allowed disabled:opacity-40",
                  active
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:bg-muted/70",
                )}
              >
                <span className="size-2 rounded-full bg-current sm:hidden" aria-hidden />
                <span className="hidden sm:inline" aria-hidden>
                  {stepLabel(step, i, steps)}
                  {done && " ✓"}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      <span className="text-sm text-muted-foreground sm:hidden">
        Step {current + 1} of {steps.length}
      </span>
    </nav>
  );
}
