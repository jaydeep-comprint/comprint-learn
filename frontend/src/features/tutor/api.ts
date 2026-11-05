import { useQuery } from "@tanstack/react-query";

import { retryUnlessClientError } from "@/features/learn/api";
import { apiFetch } from "@/lib/api";
import type { TutorReply, TutorThread } from "@/lib/types";

export const tutorKeys = {
  thread: (sessionId: string, position: number) => ["tutor", sessionId, position] as const,
};

const base = (sessionId: string, position: number) => `/api/v1/tutor/${sessionId}/${position}`;

/** One GET per question served (no model call): enabled, hints left, the messages. */
export function useTutorThread(sessionId: string | null, position: number) {
  return useQuery({
    queryKey: tutorKeys.thread(sessionId ?? "", position),
    queryFn: () => apiFetch<TutorThread>(base(sessionId ?? "", position)),
    enabled: sessionId !== null,
    retry: retryUnlessClientError,
    refetchOnWindowFocus: false,
  });
}

export function requestHint(sessionId: string, position: number, draft: string | null) {
  return apiFetch<TutorReply>(`${base(sessionId, position)}/hint`, {
    method: "POST",
    body: draft ? { draft } : {},
  });
}

export function sendMessage(
  sessionId: string,
  position: number,
  text: string,
  draft: string | null,
) {
  return apiFetch<TutorReply>(`${base(sessionId, position)}/messages`, {
    method: "POST",
    body: draft ? { text, draft } : { text },
  });
}

export const MAX_MESSAGE = 500;
export const MAX_DRAFT = 10_000;
export const RUNG_NAMES: Record<number, string> = {
  1: "Worked example",
  2: "Prerequisite",
  3: "Something to try",
};
