import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/lib/api";
import type {
  CheckSubmitted,
  CourseSummary,
  Lesson,
  LessonProgress,
  LockedPrereq,
  Outline,
  StudentCourse,
} from "@/lib/types";

export const learnKeys = {
  all: ["learn"] as const,
  courses: ["learn", "courses"] as const,
  outline: (course: string) => ["learn", "outline", course] as const,
  lesson: (concept: string) => ["learn", "lesson", concept] as const,
};

/** 403/404 are answers, not glitches: don't retry them. */
function retryUnlessClientError(count: number, error: unknown): boolean {
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
