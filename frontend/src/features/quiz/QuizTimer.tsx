import { Timer } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { formatClock } from "@/features/quiz/api";
import { cn } from "@/lib/utils";

const WARN_SECONDS = 60;

/** The quiz's sticky countdown, from the server's `seconds_left` (immune to client clock skew).
 * Calls `onExpire` once when it reaches 0. */
export function QuizTimer({
  secondsLeft,
  onExpire,
}: {
  secondsLeft: number;
  onExpire: () => void;
}) {
  const [left, setLeft] = useState(secondsLeft);
  const expired = useRef(false);
  const expire = useRef(onExpire);
  useEffect(() => {
    expire.current = onExpire;
  });

  useEffect(() => {
    const start = performance.now();
    const tick = () => {
      const now = Math.max(0, secondsLeft - (performance.now() - start) / 1000);
      setLeft(now);
      if (now <= 0 && !expired.current) {
        expired.current = true;
        expire.current();
      }
    };
    tick();
    const handle = window.setInterval(tick, 250);
    return () => window.clearInterval(handle);
  }, [secondsLeft]);

  const warn = left < WARN_SECONDS;
  return (
    <div
      role="timer"
      aria-label={`${formatClock(Math.ceil(left))} left`}
      className={cn(
        "sticky top-0 z-10 -mx-4 flex items-center justify-center gap-2 border-b bg-background/95 px-4 py-2 font-semibold tabular-nums backdrop-blur sm:mx-0 sm:rounded-b-lg",
        warn && "border-warning/50 bg-warning/10 text-warning",
      )}
      data-warning={warn || undefined}
    >
      <Timer className="size-4" aria-hidden />
      {formatClock(Math.ceil(left))}
    </div>
  );
}
