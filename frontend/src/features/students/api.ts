import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import type { Slip, Student, UserStatus } from "@/lib/types";

export function useStudents(q: string, classId?: string) {
  const params = new URLSearchParams();
  if (q.trim()) params.set("q", q.trim());
  if (classId) params.set("class_id", classId);
  const query = params.toString();
  return useQuery({
    queryKey: ["students", { q: q.trim(), classId }],
    queryFn: () => apiFetch<Student[]>(`/api/v1/students${query ? `?${query}` : ""}`),
    placeholderData: (previous) => previous,
  });
}

function useInvalidateStudents() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["students"] }),
      queryClient.invalidateQueries({ queryKey: ["classes"] }),
    ]);
}

export function useResetPassword() {
  return useMutation({
    mutationFn: ({ id }: { id: string; displayName: string }) =>
      apiFetch<Omit<Slip, "display_name">>(`/api/v1/students/${id}/reset-password`, {
        method: "POST",
      }),
  });
}

export function useUpdateStudent() {
  const invalidate = useInvalidateStudents();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; status?: UserStatus; display_name?: string }) =>
      apiFetch<Student>(`/api/v1/students/${id}`, { method: "PATCH", body }),
    onSuccess: invalidate,
  });
}
