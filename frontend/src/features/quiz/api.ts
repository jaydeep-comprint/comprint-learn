import { useQuery } from "@tanstack/react-query";

import { type AnswerBody, retryUnlessClientError } from "@/features/learn/api";
import { ApiError, apiFetch } from "@/lib/api";
import type { Question, QuizResult, QuizSaved, QuizState } from "@/lib/types";

export const quizKeys = {
  all: ["quiz"] as const,
  current: ["quiz", "current"] as const,
  state: (id: string) => ["quiz", id] as const,
  question: (id: string) => ["quiz", id, "question"] as const,
  result: (id: string) => ["quiz", id, "result"] as const,
};

export function quizPath(id: string): string {
  return `/quiz/${id}`;
}

/** The pending or active quiz, or null (spec 007). */
export function useCurrentQuiz() {
  return useQuery({
    queryKey: quizKeys.current,
    queryFn: () => apiFetch<QuizState | null>("/api/v1/quizzes/current"),
    retry: retryUnlessClientError,
  });
}

export function useQuizState(id: string) {
  return useQuery({
    queryKey: quizKeys.state(id),
    queryFn: () => apiFetch<QuizState>(`/api/v1/quizzes/${id}`),
    retry: retryUnlessClientError,
    refetchOnWindowFocus: false,
  });
}

export function startQuiz(id: string) {
  return apiFetch<QuizState>(`/api/v1/quizzes/${id}/start`, { method: "POST", body: {} });
}

export function useQuizQuestion(id: string, enabled: boolean) {
  return useQuery({
    queryKey: quizKeys.question(id),
    queryFn: () => apiFetch<Question>(`/api/v1/quizzes/${id}/question`),
    retry: retryUnlessClientError,
    enabled,
    refetchOnWindowFocus: false,
    staleTime: Infinity,
  });
}

export function submitQuizAnswer(id: string, body: AnswerBody) {
  return apiFetch<QuizSaved>(`/api/v1/quizzes/${id}/answer`, { method: "POST", body });
}

export function useQuizResult(id: string, enabled: boolean) {
  return useQuery({
    queryKey: quizKeys.result(id),
    queryFn: () => apiFetch<QuizResult>(`/api/v1/quizzes/${id}/result`),
    retry: retryUnlessClientError,
    enabled,
    refetchOnWindowFocus: false,
  });
}

/** "9:12" */
export function formatClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** The quiz id from a 409 `quiz_pending` body. */
export function pendingQuizId(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  const body = error.body as { quiz_id?: string } | undefined;
  return body?.quiz_id ?? null;
}
