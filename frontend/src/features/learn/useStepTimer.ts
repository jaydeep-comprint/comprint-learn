import { useEffect, useRef } from "react";

export const MAX_STEP_SECONDS = 600;

export type StepReport = (step: string, seconds: number, opts: { keepalive: boolean }) => void;

/**
 * Measures active seconds on `step`: time it is on screen while the tab is visible. Reports them
 * when the step changes or unmounts, and when the tab is hidden / the page is left (`keepalive`).
 * Each report is capped at MAX_STEP_SECONDS; nothing is reported for 0 s. `step = null` disables.
 */
export function useStepTimer(step: string | null, report: StepReport) {
  const reportRef = useRef(report);
  useEffect(() => {
    reportRef.current = report;
  }, [report]);

  useEffect(() => {
    if (step === null) return;
    let activeMs = 0;
    let since: number | null = document.visibilityState === "hidden" ? null : performance.now();

    const flush = (keepalive: boolean) => {
      if (since !== null) activeMs += performance.now() - since;
      since = document.visibilityState === "hidden" ? null : performance.now();
      const seconds = Math.min(MAX_STEP_SECONDS, Math.round(activeMs / 1000));
      activeMs = 0;
      if (seconds > 0) reportRef.current(step, seconds, { keepalive });
    };
    const onVisibility = () => {
      if (document.visibilityState === "hidden") flush(true);
      else since = performance.now();
    };
    const onPageHide = () => flush(true);

    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", onPageHide);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", onPageHide);
      flush(false);
    };
  }, [step]);
}
