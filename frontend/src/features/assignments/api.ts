import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { retryUnlessClientError } from "@/features/learn/api";
import { apiFetch } from "@/lib/api";
import type {
  AssignmentDetail,
  AssignmentInput,
  AssignmentSummary,
  MyAssignment,
} from "@/lib/types";

export const assignmentKeys = {
  list: (classId: string) => ["classes", classId, "assignments"] as const,
  detail: (classId: string, id: string) => ["classes", classId, "assignments", id] as const,
  mine: ["me", "assignments"] as const,
};

const base = (classId: string) => `/api/v1/classes/${classId}/assignments`;

export function useAssignments(classId: string) {
  return useQuery({
    queryKey: assignmentKeys.list(classId),
    queryFn: () => apiFetch<AssignmentSummary[]>(base(classId)),
    staleTime: 60_000,
    retry: retryUnlessClientError,
  });
}

export function useAssignment(classId: string, id: string | null) {
  return useQuery({
    queryKey: assignmentKeys.detail(classId, id ?? ""),
    queryFn: () => apiFetch<AssignmentDetail>(`${base(classId)}/${id}`),
    enabled: id !== null,
    retry: retryUnlessClientError,
  });
}

export function useMyAssignments() {
  return useQuery({
    queryKey: assignmentKeys.mine,
    queryFn: () => apiFetch<MyAssignment[]>("/api/v1/me/assignments"),
    retry: retryUnlessClientError,
  });
}

function useInvalidate(classId: string) {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["classes", classId] }),
      queryClient.invalidateQueries({ queryKey: assignmentKeys.mine }),
    ]);
}

export function useSaveAssignment(classId: string) {
  const invalidate = useInvalidate(classId);
  return useMutation({
    mutationFn: ({ id, body }: { id: string | null; body: AssignmentInput }) =>
      id === null
        ? apiFetch<AssignmentSummary>(base(classId), { method: "POST", body })
        : apiFetch<AssignmentSummary>(`${base(classId)}/${id}`, { method: "PATCH", body }),
    onSuccess: invalidate,
  });
}

export function useDeleteAssignment(classId: string) {
  const invalidate = useInvalidate(classId);
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(`${base(classId)}/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}
