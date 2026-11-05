import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router";

import { retryUnlessClientError } from "@/features/learn/api";
import { apiFetch } from "@/lib/api";
import type {
  ActivityRow,
  ClassOverview,
  ConceptDetail,
  ConceptStat,
  DashboardWindow,
  Heatmap,
  MisconceptionStat,
  StudentDetail,
  TeacherOutline,
  ThreadDetail,
  ThreadRow,
} from "@/lib/types";

/** Spec 010: dashboard reads are cached for a minute; assignment changes invalidate them. */
const STALE = 60_000;
const WINDOWS: DashboardWindow[] = ["7d", "30d", "all"];

export const dashboardKeys = {
  all: (id: string) => ["classes", id] as const,
  overview: (id: string, w: DashboardWindow) => ["classes", id, "overview", w] as const,
  concepts: (id: string, w: DashboardWindow) => ["classes", id, "concepts", w] as const,
  concept: (id: string, ref: string, w: DashboardWindow) =>
    ["classes", id, "concept", ref, w] as const,
  misconceptions: (id: string, w: DashboardWindow) => ["classes", id, "misconceptions", w] as const,
  heatmap: (id: string) => ["classes", id, "heatmap"] as const,
  student: (id: string, sid: string) => ["classes", id, "student", sid] as const,
  outline: (id: string, sid: string) => ["classes", id, "student", sid, "outline"] as const,
  activity: (id: string, sid: string) => ["classes", id, "student", sid, "activity"] as const,
  threads: (id: string, sid: string) => ["classes", id, "student", sid, "tutor"] as const,
  thread: (id: string, sid: string, tid: string) =>
    ["classes", id, "student", sid, "tutor", tid] as const,
};

/** The analytics window, kept in the URL (`?window=30d`). */
export function useWindow(): [DashboardWindow, (w: DashboardWindow) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get("window");
  const value = WINDOWS.includes(raw as DashboardWindow) ? (raw as DashboardWindow) : "7d";
  const set = (w: DashboardWindow) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (w === "7d") next.delete("window");
        else next.set("window", w);
        return next;
      },
      { replace: true },
    );
  return [value, set];
}

const base = (id: string) => `/api/v1/classes/${id}`;

export function useOverview(id: string, w: DashboardWindow) {
  return useQuery({
    queryKey: dashboardKeys.overview(id, w),
    queryFn: () => apiFetch<ClassOverview>(`${base(id)}/overview?window=${w}`),
    staleTime: STALE,
    retry: retryUnlessClientError,
  });
}

export function useConceptStats(id: string, w: DashboardWindow, enabled = true) {
  return useQuery({
    queryKey: dashboardKeys.concepts(id, w),
    queryFn: () => apiFetch<ConceptStat[]>(`${base(id)}/concepts?window=${w}`),
    staleTime: STALE,
    enabled,
    retry: retryUnlessClientError,
  });
}

export function useConceptDetail(id: string, ref: string | null, w: DashboardWindow) {
  return useQuery({
    queryKey: dashboardKeys.concept(id, ref ?? "", w),
    queryFn: () => apiFetch<ConceptDetail>(`${base(id)}/concepts/${ref}?window=${w}`),
    staleTime: STALE,
    enabled: ref !== null,
    retry: retryUnlessClientError,
  });
}

export function useMisconceptions(id: string, w: DashboardWindow, enabled = true) {
  return useQuery({
    queryKey: dashboardKeys.misconceptions(id, w),
    queryFn: () => apiFetch<MisconceptionStat[]>(`${base(id)}/misconceptions?window=${w}`),
    staleTime: STALE,
    enabled,
    retry: retryUnlessClientError,
  });
}

export function useHeatmap(id: string) {
  return useQuery({
    queryKey: dashboardKeys.heatmap(id),
    queryFn: () => apiFetch<Heatmap>(`${base(id)}/heatmap`),
    staleTime: STALE,
    retry: retryUnlessClientError,
  });
}

export function useStudentDetail(id: string, sid: string) {
  return useQuery({
    queryKey: dashboardKeys.student(id, sid),
    queryFn: () => apiFetch<StudentDetail>(`${base(id)}/students/${sid}`),
    staleTime: STALE,
    retry: retryUnlessClientError,
  });
}

export function useStudentOutline(id: string, sid: string) {
  return useQuery({
    queryKey: dashboardKeys.outline(id, sid),
    queryFn: () => apiFetch<TeacherOutline>(`${base(id)}/students/${sid}/outline`),
    staleTime: STALE,
    retry: retryUnlessClientError,
  });
}

const PAGE = 50;

export function useActivity(id: string, sid: string) {
  return useInfiniteQuery({
    queryKey: dashboardKeys.activity(id, sid),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      apiFetch<ActivityRow[]>(
        `${base(id)}/students/${sid}/activity` +
          (pageParam ? `?before=${encodeURIComponent(pageParam)}` : ""),
      ),
    getNextPageParam: (last) => (last.length < PAGE ? null : (last.at(-1)?.ended_at ?? null)),
    staleTime: STALE,
    retry: retryUnlessClientError,
  });
}

export function useThreads(id: string, sid: string) {
  return useQuery({
    queryKey: dashboardKeys.threads(id, sid),
    queryFn: () => apiFetch<ThreadRow[]>(`${base(id)}/students/${sid}/tutor`),
    staleTime: STALE,
    retry: retryUnlessClientError,
  });
}

export function useThread(id: string, sid: string, tid: string | null) {
  return useQuery({
    queryKey: dashboardKeys.thread(id, sid, tid ?? ""),
    queryFn: () => apiFetch<ThreadDetail>(`${base(id)}/students/${sid}/tutor/${tid}`),
    staleTime: STALE,
    enabled: tid !== null,
    retry: retryUnlessClientError,
  });
}
