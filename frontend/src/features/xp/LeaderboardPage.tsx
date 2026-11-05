import { Trophy } from "lucide-react";
import { useParams } from "react-router";

import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";

import { useLeaderboard } from "./api";
import { LeaderboardTable } from "./LeaderboardTable";

/** `/leaderboard/:classId` (students): this week's class ranking, while the teacher has it on. */
export function LeaderboardPage() {
  const { classId = "" } = useParams();
  const board = useLeaderboard(classId);
  if (board.isPending) {
    return (
      <div className="mx-auto max-w-2xl space-y-3" aria-busy>
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40" />
      </div>
    );
  }
  if (board.isError) {
    const missing = board.error instanceof ApiError && board.error.status === 404;
    return (
      <div className="mx-auto flex max-w-md flex-col items-center gap-3 py-16 text-center">
        <Trophy className="size-10 text-muted-foreground" aria-hidden />
        <p className="text-muted-foreground">
          {missing ? "This leaderboard isn't available" : "Couldn't load the leaderboard."}
        </p>
      </div>
    );
  }
  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title={board.data.class_name} description="This week (Mon–Sun)" />
      <LeaderboardTable board={board.data} />
    </div>
  );
}
