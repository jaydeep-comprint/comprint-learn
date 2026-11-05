import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { retryUnlessClientError } from "@/features/learn/api";
import { ApiError, apiFetch } from "@/lib/api";
import type { DashboardWindow, SummaryState, TeacherSummary } from "@/lib/types";

/** Spec 011. Under `["classes", id]`, so assignment changes refresh staleness too. */
export const summaryKeys = {
  class: (id: string, w: DashboardWindow) => ["classes", id, "summary", w] as const,
  student: (id: string, sid: string) => ["classes", id, "student", sid, "summary"] as const,
};

export type SummaryTarget = { classId: string; window: DashboardWindow; studentId?: string };

function path({ classId, window, studentId }: SummaryTarget): string {
  const base = `/api/v1/classes/${classId}`;
  return studentId ? `${base}/students/${studentId}/summary` : `${base}/summary?window=${window}`;
}

function key(t: SummaryTarget) {
  return t.studentId
    ? summaryKeys.student(t.classId, t.studentId)
    : summaryKeys.class(t.classId, t.window);
}

export function useSummaryState(t: SummaryTarget) {
  return useQuery({
    queryKey: key(t),
    queryFn: () => apiFetch<SummaryState>(path(t)),
    staleTime: 60_000,
    retry: retryUnlessClientError,
  });
}

export function useGenerateSummary(t: SummaryTarget) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<TeacherSummary>(path(t), { method: "POST" }),
    onSuccess: (summary) => {
      queryClient.setQueryData<SummaryState>(key(t), (prev) =>
        prev ? { ...prev, summary, stale: false, can_regenerate: false, blocked: "fresh" } : prev,
      );
      void queryClient.invalidateQueries({ queryKey: key(t) });
    },
    onError: () => void queryClient.invalidateQueries({ queryKey: key(t) }),
  });
}

/** The message for a failed Generate / Regenerate (client state only, spec 011). */
export function generateError(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "Couldn't reach the server. Check your connection and try again.";
  }
  switch (error.code) {
    case "teacher_ai_daily_cap":
      return "You've used today's 10 summaries. More after midnight.";
    case "school_ai_daily_cap":
      return "Your school has used today's summaries. More after midnight.";
    case "summary_busy":
      return "A summary is already being written. Try again in a minute.";
    case "summary_fresh":
      return "Nothing has changed since the last summary.";
    case "summary_failed":
      return "Couldn't write a summary this time. The dashboard numbers are unaffected.";
    case "teacher_ai_unavailable":
      return "AI summaries aren't available right now.";
    case "class_archived":
      return "This class is archived.";
    case "not_enough_data":
      return "Not enough activity yet for a useful summary. Check back after a few lessons.";
    default:
      return error.message || "Something went wrong. Please try again.";
  }
}

export const BLOCKED_REASONS: Record<string, string> = {
  fresh: "Nothing has changed since the last summary.",
  busy: "A summary is already being written.",
  teacher_cap: "You've used today's 10 summaries. More after midnight.",
  school_cap: "Your school has used today's summaries. More after midnight.",
  archived: "This class is archived.",
  not_enough_data: "Not enough activity yet.",
};
