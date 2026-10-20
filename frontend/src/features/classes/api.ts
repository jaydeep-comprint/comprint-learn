import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import type { ClassStudent, CreatedStudent, SchoolClass, Subject } from "@/lib/types";

export const classKeys = {
  all: ["classes"] as const,
  list: (mine: boolean, archived: boolean) => ["classes", "list", { mine, archived }] as const,
  detail: (id: string) => ["classes", "detail", id] as const,
  students: (id: string) => ["classes", "students", id] as const,
};

export function useClasses(mine: boolean, archived: boolean) {
  return useQuery({
    queryKey: classKeys.list(mine, archived),
    queryFn: () => apiFetch<SchoolClass[]>(`/api/v1/classes?mine=${mine}&archived=${archived}`),
  });
}

export function useClass(id: string) {
  return useQuery({
    queryKey: classKeys.detail(id),
    queryFn: () => apiFetch<SchoolClass>(`/api/v1/classes/${id}`),
  });
}

export function useClassStudents(id: string) {
  return useQuery({
    queryKey: classKeys.students(id),
    queryFn: () => apiFetch<ClassStudent[]>(`/api/v1/classes/${id}/students`),
  });
}

export type ClassInput = { name: string; subject: Subject; grade: 9 | 10 };

function useInvalidateClasses() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: classKeys.all }),
      queryClient.invalidateQueries({ queryKey: ["students"] }),
    ]);
}

export function useCreateClass() {
  const invalidate = useInvalidateClasses();
  return useMutation({
    mutationFn: (body: ClassInput) =>
      apiFetch<SchoolClass>("/api/v1/classes", { method: "POST", body }),
    onSuccess: invalidate,
  });
}

export function useUpdateClass(id: string) {
  const invalidate = useInvalidateClasses();
  return useMutation({
    mutationFn: (body: Partial<ClassInput> & { archived?: boolean }) =>
      apiFetch<SchoolClass>(`/api/v1/classes/${id}`, { method: "PATCH", body }),
    onSuccess: invalidate,
  });
}

export function useClassTeacher(id: string) {
  const invalidate = useInvalidateClasses();
  return useMutation({
    mutationFn: ({ userId, add }: { userId: string; add: boolean }) =>
      apiFetch<void>(`/api/v1/classes/${id}/teachers/${userId}`, {
        method: add ? "PUT" : "DELETE",
      }),
    onSuccess: invalidate,
  });
}

export function useCreateStudents(id: string) {
  const invalidate = useInvalidateClasses();
  return useMutation({
    mutationFn: (displayNames: string[]) =>
      apiFetch<CreatedStudent[]>(`/api/v1/classes/${id}/students`, {
        method: "POST",
        body: { display_names: displayNames },
      }),
    onSuccess: invalidate,
  });
}

export function useEnroll(id: string) {
  const invalidate = useInvalidateClasses();
  return useMutation({
    mutationFn: (studentIds: string[]) =>
      apiFetch<void>(`/api/v1/classes/${id}/enrollments`, {
        method: "POST",
        body: { student_ids: studentIds },
      }),
    onSuccess: invalidate,
  });
}

export function useUnenroll(id: string) {
  const invalidate = useInvalidateClasses();
  return useMutation({
    mutationFn: (studentId: string) =>
      apiFetch<void>(`/api/v1/classes/${id}/enrollments/${studentId}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}
