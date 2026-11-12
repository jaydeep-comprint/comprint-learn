import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiDownload, apiFetch } from "@/lib/api";
import type { AuditAction, AuditPage, Notice, Student } from "@/lib/types";

/** Spec 014: at most this many students per consent request (all-or-nothing on the server). */
export const MAX_CONSENT_SELECTION = 200;

export function useNotice() {
  return useQuery({
    queryKey: ["privacy", "notice"],
    queryFn: () => apiFetch<Notice>("/api/v1/privacy/notice"),
    staleTime: Infinity,
  });
}

export type ConsentAction = "record" | "withdraw";

export function useSetConsent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ ids, action }: { ids: string[]; action: ConsentAction }) =>
      apiFetch<Student[]>("/api/v1/students/consent", {
        method: "POST",
        body: { student_ids: ids, action },
      }),
    // Rosters, the Students page and student pages (["classes", id, "student", sid]).
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ["classes"] }),
        queryClient.invalidateQueries({ queryKey: ["students"] }),
        queryClient.invalidateQueries({ queryKey: ["audit"] }),
      ]),
  });
}

export function useAudit(action: AuditAction | null) {
  return useInfiniteQuery({
    queryKey: ["audit", { action }],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams();
      if (action) params.set("action", action);
      if (pageParam) params.set("before", pageParam);
      const query = params.toString();
      return apiFetch<AuditPage>(`/api/v1/audit${query ? `?${query}` : ""}`);
    },
    getNextPageParam: (last) => last.next_before,
  });
}

function useInvalidatePeople() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["classes"] }),
      queryClient.invalidateQueries({ queryKey: ["students"] }),
      queryClient.invalidateQueries({ queryKey: ["audit"] }),
    ]);
}

/** Spec 014: schedule an erasure (admins); the username must be typed to confirm. */
export function useRequestErasure() {
  const invalidate = useInvalidatePeople();
  return useMutation({
    mutationFn: ({ id, confirmUsername }: { id: string; confirmUsername: string }) =>
      apiFetch<Student>(`/api/v1/students/${id}/erasure`, {
        method: "POST",
        body: { confirm_username: confirmUsername },
      }),
    onSuccess: invalidate,
  });
}

export function useCancelErasure() {
  const invalidate = useInvalidatePeople();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<Student>(`/api/v1/students/${id}/erasure`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

/** Spec 014: the student's data as a JSON file (admins; the server logs the download). */
export function useDownloadExport() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, username }: { id: string; username: string }) =>
      apiDownload(`/api/v1/students/${id}/export`, `student-${username}.json`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["audit"] }),
  });
}
