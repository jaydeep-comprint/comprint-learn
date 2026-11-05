import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { retryUnlessClientError } from "@/features/learn/api";
import { apiFetch } from "@/lib/api";
import type { Leaderboard, Subject, XpSummary } from "@/lib/types";

export const xpKeys = {
  me: ["me", "xp"] as const,
  leaderboard: (classId: string) => ["leaderboard", classId] as const,
};

/** The student's XP chip and popover data (`GET /me/xp`). */
export function useXpSummary() {
  return useQuery({
    queryKey: xpKeys.me,
    queryFn: () => apiFetch<XpSummary>("/api/v1/me/xp"),
    retry: retryUnlessClientError,
  });
}

export function useSetGoal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ subject, goal }: { subject: Subject; goal: number | null }) =>
      apiFetch<XpSummary>(`/api/v1/me/goals/${subject}`, { method: "PUT", body: { goal } }),
    onSuccess: (summary) => queryClient.setQueryData(xpKeys.me, summary),
  });
}

export function useLeaderboard(classId: string) {
  return useQuery({
    queryKey: xpKeys.leaderboard(classId),
    queryFn: () => apiFetch<Leaderboard>(`/api/v1/classes/${classId}/leaderboard`),
    retry: retryUnlessClientError,
  });
}

export const GOAL_STEPS = Array.from({ length: 12 }, (_, i) => (i + 1) * 5); // 5…60
