import type { StepResult } from "@/lib/types";

/** ceil(0.75 × steps) correct, the last one included (backend/app/grading/multistep.py). */
export function multistepPassed(results: StepResult[], steps: number): boolean {
  const right = results.filter((r) => r.correct).length;
  return (
    results.length === steps && right >= Math.ceil(0.75 * steps) && !!results[steps - 1]?.correct
  );
}
