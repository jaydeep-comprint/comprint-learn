import { Flame } from "lucide-react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { useXpSummary } from "./api";
import { XpPopover } from "./XpPopover";

/** Header chip (students): streak + today's XP / today's goals. Hidden on error; never blocks. */
export function XpChip() {
  const { data, isPending, isError } = useXpSummary();
  if (isPending) return <Skeleton className="h-8 w-16 sm:w-24" data-testid="xp-chip-loading" />;
  if (isError) return null;
  // Subjects without a goal (e.g. a brush-up with no class) don't count towards the goals.
  const withGoal = data.today.filter((t) => t.goal !== null);
  const xp = (withGoal.length ? withGoal : data.today).reduce((n, t) => n + t.xp, 0);
  const goal = withGoal.reduce((n, t) => n + (t.goal ?? 0), 0);
  const met = data.streak.today_met;
  const label = goal
    ? `Streak ${data.streak.days} days, ${xp} of ${goal} XP today`
    : `Streak ${data.streak.days} days, ${xp} XP today`;
  return (
    <Popover>
      <PopoverTrigger
        aria-label={label}
        className="flex h-8 shrink-0 items-center gap-1 rounded-full border px-2.5 text-sm font-medium tabular-nums hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
      >
        <Flame
          aria-hidden
          data-met={met}
          className={cn(
            "size-4",
            met ? "fill-orange-400 text-orange-500" : "text-muted-foreground",
          )}
        />
        <span>{data.streak.days}</span>
        <span className="hidden sm:inline" data-testid="xp-chip-today">
          · {goal ? `${xp}/${goal}` : `${xp} XP`}
        </span>
      </PopoverTrigger>
      <PopoverContent>
        <XpPopover summary={data} />
      </PopoverContent>
    </Popover>
  );
}
