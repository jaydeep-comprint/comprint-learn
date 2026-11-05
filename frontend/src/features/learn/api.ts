import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/lib/api";
import type {
  AnswerResult,
  CheckSubmitted,
  CourseSummary,
  Lesson,
  LessonProgress,
  LockedPrereq,
  Outline,
  Question,
  RemediationInfo,
  StudentCourse,
  TestOutput,
} from "@/lib/types";

export const learnKeys = {
  all: ["learn"] as const,
  courses: ["learn", "courses"] as const,
  outline: (course: string) => ["learn", "outline", course] as const,
  lesson: (concept: string) => ["learn", "lesson", concept] as const,
  question: (concept: string, kp: string) => ["learn", "question", concept, kp] as const,
  practice: (concept: string, again: boolean) =>
    ["learn", "practice", concept, again ? "again" : "attempt"] as const,
  remediation: (id: string) => ["learn", "remediation", id] as const,
  remediationQuestion: (id: string) => ["learn", "remediation", id, "question"] as const,
};

/** 403/404 are answers, not glitches: don't retry them. */
export function retryUnlessClientError(count: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return count < 2;
}

export function useStudentCourses() {
  return useQuery({
    queryKey: learnKeys.courses,
    queryFn: () => apiFetch<StudentCourse[]>("/api/v1/learn/courses"),
    retry: retryUnlessClientError,
  });
}

export function useOutline(course: string) {
  return useQuery({
    queryKey: learnKeys.outline(course),
    queryFn: () => apiFetch<Outline>(`/api/v1/learn/courses/${course}/outline`),
    retry: retryUnlessClientError,
  });
}

export function useLesson(concept: string) {
  return useQuery({
    queryKey: learnKeys.lesson(concept),
    queryFn: () => apiFetch<Lesson>(`/api/v1/learn/concepts/${concept}`),
    retry: retryUnlessClientError,
    // Always fresh on open (resume point, stored check result); LessonPage waits for that fetch.
    // A background refetch must not move the student, so no refetch on focus.
    refetchOnMount: "always",
    refetchOnWindowFocus: false,
  });
}

/** All courses (global content), for the teacher's "View course" button. */
export function useAllCourses() {
  return useQuery({
    queryKey: ["courses"],
    queryFn: () => apiFetch<CourseSummary[]>("/api/v1/courses"),
    staleTime: 5 * 60_000,
  });
}

/** The unfinished prerequisites from a `concept_locked` error, or null for any other error. */
export function lockedPrereqs(error: unknown): LockedPrereq[] | null {
  if (!(error instanceof ApiError) || error.code !== "concept_locked") return null;
  const body = error.body as { prereqs?: LockedPrereq[] } | undefined;
  return body?.prereqs ?? [];
}

export function useSubmitCheck(concept: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { option_id: string; time_taken_ms: number }) =>
      apiFetch<CheckSubmitted>(`/api/v1/learn/concepts/${concept}/check`, {
        method: "POST",
        body,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: learnKeys.courses }),
  });
}

/** What a student enters (one question, or one step of a multi-step problem). */
export type AnswerFields = {
  response?: string;
  /** Numeric with a unit only. */
  unit?: string;
  /** Multi-step: the step answered. */
  step?: number;
  /** Code: the source and one output per test (authored order). */
  code?: string;
  outputs?: TestOutput[];
};

export type AnswerBody = AnswerFields & {
  position: number;
  /** The session the question was shown in: an answer from an earlier one is never graded
   * against the current one (another tab, a practice retry). */
  session_id?: string;
  time_taken_ms: number;
  item_id?: string;
  seed?: number | null;
};

/** The current question of a KP (the same one on reload). 409s are panels, not glitches. */
export function useKpQuestion(concept: string, kp: string, enabled = true) {
  return useQuery({
    queryKey: learnKeys.question(concept, kp),
    queryFn: () => apiFetch<Question>(`/api/v1/learn/concepts/${concept}/kps/${kp}/question`),
    retry: retryUnlessClientError,
    enabled,
    refetchOnWindowFocus: false,
    staleTime: Infinity,
  });
}

export function submitKpAnswer(concept: string, kp: string, body: AnswerBody) {
  return apiFetch<AnswerResult>(`/api/v1/learn/concepts/${concept}/kps/${kp}/answer`, {
    method: "POST",
    body,
  });
}

/** The lesson's Practice step (spec 006). `again`: re-practice a learned concept (writes nothing). */
export function usePracticeQuestion(concept: string, again = false, enabled = true) {
  return useQuery({
    queryKey: learnKeys.practice(concept, again),
    queryFn: () =>
      apiFetch<Question>(
        `/api/v1/learn/concepts/${concept}/practice/question${again ? "?again=true" : ""}`,
      ),
    retry: retryUnlessClientError,
    enabled,
    refetchOnWindowFocus: false,
    staleTime: Infinity,
  });
}

export function submitPracticeAnswer(concept: string, body: AnswerBody, again = false) {
  return apiFetch<AnswerResult>(
    `/api/v1/learn/concepts/${concept}/practice/answer${again ? "?again=true" : ""}`,
    { method: "POST", body },
  );
}

export function useRemediation(id: string) {
  return useQuery({
    queryKey: learnKeys.remediation(id),
    queryFn: () => apiFetch<RemediationInfo>(`/api/v1/learn/remediations/${id}`),
    retry: retryUnlessClientError,
  });
}

export function useRemediationQuestion(id: string, enabled = true) {
  return useQuery({
    queryKey: learnKeys.remediationQuestion(id),
    queryFn: () => apiFetch<Question>(`/api/v1/learn/remediations/${id}/question`),
    retry: retryUnlessClientError,
    enabled,
    refetchOnWindowFocus: false,
    staleTime: Infinity,
  });
}

export function submitRemediationAnswer(id: string, body: AnswerBody) {
  return apiFetch<AnswerResult>(`/api/v1/learn/remediations/${id}/answer`, {
    method: "POST",
    body,
  });
}

/** The 409 code of a KP/remediation request (`kp_waiting`, `kp_order`, ...), else null. */
export function conflictCode(error: unknown): string | null {
  return error instanceof ApiError && error.status === 409 ? (error.code ?? null) : null;
}

// Progress posts for one lesson run one after another, so the server sees steps in the order the
// student moved through them (`last_step` is the resume point). A post started while the page is
// going away (`keepalive`) skips the queue: there may be no "later" to run it in.
const queues = new Map<string, Promise<unknown>>();

async function postOnce(
  concept: string,
  step: string,
  activeSeconds: number,
  keepalive: boolean,
): Promise<LessonProgress | undefined> {
  const send = () =>
    apiFetch<LessonProgress | undefined>(`/api/v1/learn/concepts/${concept}/progress`, {
      method: "POST",
      body: { step, active_seconds: activeSeconds },
      keepalive,
    });
  try {
    return await send();
  } catch (error) {
    if (error instanceof ApiError && error.status < 500) return undefined;
    try {
      return await send(); // one silent retry; never block reading
    } catch {
      return undefined;
    }
  }
}

/** Report a step as seen (and its active seconds). Errors are swallowed. Staff get 204. */
export function postProgress(
  concept: string,
  step: string,
  activeSeconds: number,
  { keepalive = false }: { keepalive?: boolean } = {},
): Promise<LessonProgress | undefined> {
  if (keepalive) return postOnce(concept, step, activeSeconds, true);
  const previous = queues.get(concept) ?? Promise.resolve();
  const next = previous.then(() => postOnce(concept, step, activeSeconds, false));
  queues.set(
    concept,
    next.catch(() => undefined),
  );
  return next;
}
