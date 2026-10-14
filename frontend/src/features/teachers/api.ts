import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import type { Teacher, UserStatus } from "@/lib/types";

const KEY = ["teachers"] as const;

export function useTeachers() {
  return useQuery({ queryKey: KEY, queryFn: () => apiFetch<Teacher[]>("/api/v1/teachers") });
}

function useInvalidate() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: KEY }),
      queryClient.invalidateQueries({ queryKey: ["me"] }),
    ]);
}

export function useInviteTeacher() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: { email: string; display_name: string }) =>
      apiFetch<Teacher>("/api/v1/teachers/invite", { method: "POST", body }),
    onSuccess: invalidate,
  });
}

export function useResendInvite() {
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<void>(`/api/v1/teachers/${id}/resend-invite`, { method: "POST" }),
  });
}

export function useUpdateTeacher() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; is_admin?: boolean; status?: UserStatus }) =>
      apiFetch<Teacher>(`/api/v1/teachers/${id}`, { method: "PATCH", body }),
    onSuccess: invalidate,
  });
}
