import { Check } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { errorMessage } from "@/lib/errors";
import { SUBJECT_LABELS, type XpSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

import { GOAL_STEPS, useSetGoal } from "./api";

function GoalBar({ xp, goal, met }: { xp: number; goal: number; met: boolean }) {
  const pct = Math.min(100, Math.round((xp / goal) * 100));
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted" aria-hidden>
      <div
        className={cn("h-full rounded-full", met ? "bg-emerald-500" : "bg-primary")}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function GoalSelect({ goal }: { goal: XpSummary["goals"][number] }) {
  const setGoal = useSetGoal();
  const [error, setError] = useState<string | null>(null);
  const id = `goal-${goal.subject}`;
  const value = goal.own_goal ?? goal.class_goal;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor={id}>{SUBJECT_LABELS[goal.subject]}</Label>
        <span className="text-xs text-muted-foreground">Teacher: {goal.class_goal}</span>
      </div>
      <Select
        id={id}
        value={value}
        disabled={setGoal.isPending}
        onChange={(e) => {
          const picked = Number(e.target.value);
          setError(null);
          setGoal.mutate(
            { subject: goal.subject, goal: picked === goal.class_goal ? null : picked },
            { onError: (err) => setError(errorMessage(err)) },
          );
        }}
      >
        {GOAL_STEPS.filter((n) => n >= goal.class_goal).map((n) => (
          <option key={n} value={n}>
            {n} XP
          </option>
        ))}
      </Select>
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

/** The chip's popover: today per subject, streak, week, own goals and leaderboard links. */
export function XpPopover({ summary }: { summary: XpSummary }) {
  const withGoal = summary.today.filter((t): t is typeof t & { goal: number } => t.goal !== null);
  const { days, today_met } = summary.streak;
  if (summary.goals.length === 0) {
    return (
      <div className="space-y-2 text-sm">
        <p>Join a class to get daily goals.</p>
        <p className="text-muted-foreground">This week: {summary.week_xp} XP</p>
      </div>
    );
  }
  return (
    <div className="space-y-4 text-sm">
      <section className="space-y-2" aria-label="Today">
        {withGoal.map((t) => (
          <div key={t.subject} className="space-y-1">
            <div className="flex items-center justify-between">
              <span>{SUBJECT_LABELS[t.subject]}</span>
              <span className="flex items-center gap-1 tabular-nums">
                {t.xp} / {t.goal} XP
                {t.met && <Check className="size-4 text-emerald-600" aria-label="met" />}
              </span>
            </div>
            <GoalBar xp={t.xp} goal={t.goal} met={t.met} />
          </div>
        ))}
      </section>
      <section className="space-y-0.5">
        <p className="font-medium">
          Streak: {days} {days === 1 ? "day" : "days"}
        </p>
        {!today_met && (
          <p className="text-muted-foreground">Meet today's goals to make it {days + 1}</p>
        )}
        <p className="text-muted-foreground">This week: {summary.week_xp} XP</p>
      </section>
      <section className="space-y-2" aria-label="My goals">
        <p className="font-medium">My goals</p>
        {summary.goals.map((g) => (
          <GoalSelect key={g.subject} goal={g} />
        ))}
      </section>
      {summary.leaderboards.length > 0 && (
        <section className="space-y-1" aria-label="Class leaderboards">
          <p className="font-medium">Class leaderboard</p>
          {summary.leaderboards.map((b) => (
            <Link
              key={b.class_id}
              to={`/leaderboard/${b.class_id}`}
              className="block text-primary underline-offset-4 hover:underline"
            >
              {b.class_name}
            </Link>
          ))}
        </section>
      )}
    </div>
  );
}
