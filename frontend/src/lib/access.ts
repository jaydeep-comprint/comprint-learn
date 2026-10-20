import type { Me } from "@/lib/types";

export type Access = "staff" | "admin" | "student";

export function hasAccess(me: Me, access: Access): boolean {
  if (access === "student") return me.role === "student";
  if (access === "admin") return me.role === "teacher" && me.is_admin;
  return me.role === "teacher";
}

export function roleLabel(me: Me): string {
  if (me.role === "student") return "Student";
  return me.is_admin ? "Admin" : "Teacher";
}
