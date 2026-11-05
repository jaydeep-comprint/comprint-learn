import { useQuery } from "@tanstack/react-query";

import { type AnswerBody, retryUnlessClientError } from "@/features/learn/api";
import { apiFetch } from "@/lib/api";
import type { AnswerResult, Question, ReviewQueue } from "@/lib/types";

export const reviewKeys = {
  all: ["reviews"] as const,
  queue: ["reviews", "queue"] as const,
  question: (concept: string) => ["reviews", "question", concept] as const,
};

/** The review page for a concept id ("<course>/<slug>"). */
export function reviewPath(conceptId: string): string {
  return `/review/${conceptId}`;
}

/** Today's reviews (spec 007). */
export function useReviewQueue() {
  return useQuery({
    queryKey: reviewKeys.queue,
    queryFn: () => apiFetch<ReviewQueue>("/api/v1/reviews"),
    retry: retryUnlessClientError,
  });
}

/** The review's current question (opens it when offered). 409s are panels, not glitches. */
export function useReviewQuestion(concept: string) {
  return useQuery({
    queryKey: reviewKeys.question(concept),
    queryFn: () => apiFetch<Question>(`/api/v1/reviews/${concept}/question`),
    retry: retryUnlessClientError,
    refetchOnWindowFocus: false,
    staleTime: Infinity,
  });
}

export function submitReviewAnswer(concept: string, body: AnswerBody) {
  return apiFetch<AnswerResult>(`/api/v1/reviews/${concept}/answer`, { method: "POST", body });
}
