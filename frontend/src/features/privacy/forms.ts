import type { ClassStudent } from "@/lib/types";

/** `?students=a,b` (unknown ids ignored), else every active student without consent. */
export function pickStudents(roster: ClassStudent[], param: string | null): ClassStudent[] {
  if (param === null) {
    return roster.filter((s) => s.status === "active" && !s.tutor_consent_at);
  }
  const wanted = new Set(param.split(",").filter(Boolean));
  return roster.filter((s) => wanted.has(s.id));
}
