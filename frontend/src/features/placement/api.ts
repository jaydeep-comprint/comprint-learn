import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { type AnswerBody, learnKeys, retryUnlessClientError } from "@/features/learn/api";
import { reviewKeys } from "@/features/reviews/api";
import { apiFetch } from "@/lib/api";
import type {
  DiagnosticResult,
  DiagnosticSaved,
  DiagnosticState,
  PlacementOverview,
  PlacementStudentRow,
  Question,
  StudentOutcomes,
} from "@/lib/types";

export const placementKeys = {
  tab: (classId: string) => ["classes", classId, "placement"] as const,
  student: (classId: string, sid: string) => ["classes", classId, "placement", sid] as const,
  all: ["placement"] as const,
  current: ["placement", "current"] as const,
  state: (id: string) => ["placement", id] as const,
  question: (id: string) => ["placement", id, "question"] as const,
  result: (id: string) => ["placement", id, "result"] as const,
};

export const placementPath = (id: string) => `/placement/${id}`;
export const placementResultPath = (id: string) => `/placement/${id}/result`;

const base = (classId: string) => `/api/v1/classes/${classId}/placement`;
const diag = (id: string) => `/api/v1/diagnostics/${id}`;

// --- teacher -----------------------------------------------------------------------------------

export function usePlacement(classId: string) {
  return useQuery({
    queryKey: placementKeys.tab(classId),
    queryFn: () => apiFetch<PlacementOverview>(base(classId)),
    retry: retryUnlessClientError,
  });
}

export function useStudentOutcomes(classId: string, sid: string | null) {
  return useQuery({
    queryKey: placementKeys.student(classId, sid ?? ""),
    queryFn: () => apiFetch<StudentOutcomes>(`${base(classId)}/students/${sid}`),
    enabled: sid !== null,
    retry: retryUnlessClientError,
  });
}

function useInvalidate(classId: string) {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["classes", classId] });
}

export function useSaveChapters(classId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (chapterIds: string[]) =>
      apiFetch<PlacementOverview>(`${base(classId)}/chapters`, {
        method: "PUT",
        body: { chapter_ids: chapterIds },
      }),
    onSuccess: (data) => queryClient.setQueryData(placementKeys.tab(classId), data),
  });
}

export function useSendPlacement(classId: string) {
  const invalidate = useInvalidate(classId);
  return useMutation({
    mutationFn: (studentIds: string[] | null) =>
      apiFetch<{ sent: number; skipped: number }>(`${base(classId)}/send`, {
        method: "POST",
        body: studentIds === null ? { all_students: true } : { student_ids: studentIds },
      }),
    onSuccess: invalidate,
  });
}

export function useStudentAction(classId: string) {
  const invalidate = useInvalidate(classId);
  return useMutation({
    mutationFn: ({ sid, action }: { sid: string; action: "resend" | "cancel" }) =>
      apiFetch<PlacementStudentRow>(`${base(classId)}/students/${sid}/${action}`, {
        method: "POST",
        body: {},
      }),
    onSuccess: invalidate,
  });
}

// --- student -----------------------------------------------------------------------------------

export function useCurrentDiagnostics() {
  return useQuery({
    queryKey: placementKeys.current,
    queryFn: () => apiFetch<DiagnosticState[]>("/api/v1/diagnostics/current"),
    retry: retryUnlessClientError,
  });
}

export function useDiagnostic(id: string) {
  return useQuery({
    queryKey: placementKeys.state(id),
    queryFn: () => apiFetch<DiagnosticState>(diag(id)),
    retry: retryUnlessClientError,
    refetchOnWindowFocus: false,
  });
}

export function startDiagnostic(id: string) {
  return apiFetch<DiagnosticState>(`${diag(id)}/start`, { method: "POST", body: {} });
}

export function useDiagnosticQuestion(id: string, enabled: boolean) {
  return useQuery({
    queryKey: placementKeys.question(id),
    queryFn: () => apiFetch<Question>(`${diag(id)}/question`),
    retry: retryUnlessClientError,
    enabled,
    refetchOnWindowFocus: false,
    staleTime: Infinity,
  });
}

export type DiagnosticAnswerBody = Omit<AnswerBody, "session_id"> & {
  session_id: string;
  idk?: boolean;
};

export function submitDiagnosticAnswer(id: string, body: DiagnosticAnswerBody) {
  return apiFetch<DiagnosticSaved>(`${diag(id)}/answer`, { method: "POST", body });
}

export function useDiagnosticResult(id: string) {
  return useQuery({
    queryKey: placementKeys.result(id),
    queryFn: () => apiFetch<DiagnosticResult>(`${diag(id)}/result`),
    retry: retryUnlessClientError,
    refetchOnWindowFocus: false,
  });
}

/** After a run ends: home cards, outlines and graphs show the new learned states. */
export function useAfterFinish() {
  const queryClient = useQueryClient();
  return () => {
    for (const key of [placementKeys.current, learnKeys.all, reviewKeys.all]) {
      void queryClient.invalidateQueries({ queryKey: key });
    }
  };
}
