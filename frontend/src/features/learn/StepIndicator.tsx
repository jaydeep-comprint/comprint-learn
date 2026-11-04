import { cn } from "@/lib/utils";

function stepLabel(step: string, index: number, steps: string[]): string {
  if (step === "intro") return "Intro";
  if (step === "check") return "Check";
  return String(steps.slice(0, index + 1).filter((s) => s.startsWith("kp:")).length);
}

function stepName(step: string, index: number, steps: string[]): string {
  if (step === "intro") return "Introduction";
  if (step === "check") return "Quick check";
  return `Worked example ${stepLabel(step, index, steps)}`;
}

/** Labelled dots (Intro · Check · 1 · 2 · 3); "Step k of n" on phones. Steps past `maxIndex` are
 * disabled. */
export function StepIndicator({
  steps,
  current,
  maxIndex,
  onJump,
}: {
  steps: string[];
  current: number;
  maxIndex: number;
  onJump: (index: number) => void;
}) {
  return (
    <nav aria-label="Lesson steps" className="flex items-center gap-3">
      <ol className="flex flex-wrap items-center gap-1 sm:gap-2">
        {steps.map((step, i) => {
          const active = i === current;
          return (
            <li key={step}>
              <button
                type="button"
                aria-current={active ? "step" : undefined}
                aria-label={stepName(step, i, steps)}
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
                <span className="hidden sm:inline">{stepLabel(step, i, steps)}</span>
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
