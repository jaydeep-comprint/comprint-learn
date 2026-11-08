import { lessonPath } from "@/features/learn/paths";
import type { DashboardWindow, FactLink, SummaryResource } from "@/lib/types";

/** Where a citation chip opens (spec 011 "Citation routing"); null = no link. */
export function factHref(
  link: FactLink,
  ctx: { classId: string; window: DashboardWindow; studentId?: string },
): string | null {
  const cls = `/classes/${ctx.classId}`;
  const overview = (param?: string) => {
    const q = [ctx.window === "7d" ? "" : `window=${ctx.window}`, param ?? ""].filter(Boolean);
    return q.length > 0 ? `${cls}?${q.join("&")}` : cls;
  };
  switch (link.kind) {
    case "concept":
      return link.concept ? overview(`concept=${encodeURIComponent(link.concept)}`) : null;
    case "misconception":
      return link.id ? overview(`misconception=${link.id}`) : null;
    case "student":
      return link.student_id ? `${cls}/students/${link.student_id}` : null;
    case "assignment":
      return link.id ? `${cls}/assignments?assignment=${link.id}` : null;
    case "student_section":
      return ctx.studentId ? `${cls}/students/${ctx.studentId}#${link.section ?? "stats"}` : null;
    case "overview_card":
      return `${overview()}#${link.card ?? "summary"}`;
  }
}

/** The staff lesson preview, at the KP's worked example when there is one. */
export function resourceHref(r: SummaryResource, classCourse: string | undefined): string | null {
  if (!r.available) return null;
  const course = classCourse ?? r.concept.split("/")[0] ?? "";
  const step = r.kp ? `?step=${encodeURIComponent(`kp:${r.kp}`)}` : "";
  return `${lessonPath(course, r.concept)}${step}`;
}

export function resourceLabel(r: SummaryResource): string {
  return r.kind === "lesson" ? `Lesson: ${r.title}` : `KP: ${r.title}`;
}
