import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useUpdateClass } from "@/features/classes/api";
import { errorMessage } from "@/lib/errors";
import type { SchoolClass } from "@/lib/types";

import { GOAL_STEPS, useLeaderboard } from "./api";
import { LeaderboardTable } from "./LeaderboardTable";

/** Teacher controls (spec 008): the class's daily goal, the opt-in leaderboard, and its table. */
export function MotivationCard({ cls }: { cls: SchoolClass }) {
  const update = useUpdateClass(cls.id);
  const board = useLeaderboard(cls.id);
  const save = (body: { daily_goal?: number; leaderboard_enabled?: boolean }) =>
    update.mutate(body, { onError: (err) => toast.error(errorMessage(err)) });

  return (
    <Card className="mb-6 gap-4">
      <CardHeader>
        <CardTitle>Motivation</CardTitle>
        <CardDescription>Daily XP goal and the weekly class leaderboard.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="flex flex-wrap items-end gap-6">
          <div className="space-y-1.5">
            <Label htmlFor="class-daily-goal">Daily goal</Label>
            <Select
              id="class-daily-goal"
              className="w-32"
              value={cls.daily_goal}
              disabled={update.isPending || cls.archived}
              onChange={(e) => save({ daily_goal: Number(e.target.value) })}
            >
              {GOAL_STEPS.map((n) => (
                <option key={n} value={n}>
                  {n} XP
                </option>
              ))}
            </Select>
          </div>
          <div className="max-w-sm space-y-1.5">
            <div className="flex items-center gap-2">
              <Switch
                id="class-leaderboard"
                checked={cls.leaderboard_enabled}
                disabled={update.isPending || cls.archived}
                onCheckedChange={(on) => save({ leaderboard_enabled: on })}
              />
              <Label htmlFor="class-leaderboard">Class leaderboard</Label>
            </div>
            <p className="text-xs text-muted-foreground">
              Students in this class see a weekly XP ranking. Off by default.
            </p>
          </div>
        </div>
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-medium">This week</h3>
            {!cls.leaderboard_enabled && (
              <Badge variant="outline">Off: students can't see this</Badge>
            )}
          </div>
          {board.isPending ? (
            <Skeleton className="h-24" />
          ) : board.isError ? (
            <p className="text-sm text-destructive">Couldn't load the leaderboard.</p>
          ) : (
            <LeaderboardTable board={board.data} />
          )}
        </div>
      </CardContent>
    </Card>
  );
}
