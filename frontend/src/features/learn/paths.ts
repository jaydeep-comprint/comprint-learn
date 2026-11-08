import type { LessonStatus, LockedPrereq, Outline, OutlineConcept } from "@/lib/types";

export const STATUS_LABELS: Record<LessonStatus, string> = {
  learned: "Learned",
  in_progress: "In progress",
  ready: "Ready to start",
  locked: "Locked",
};

/** `:course` is the outline the student came from (for Back and "next up"). */
export function lessonPath(course: string, conceptId: string): string {
  return `/learn/${course}/${conceptId}`;
}

/** The remediation page: a short review of a prerequisite (spec 005). */
export function brushUpPath(remediationId: string): string {
  return `/learn/brush-up/${remediationId}`;
}

/** Concept ids are "<course>/<slug>": the lesson route under its own course. */
export function conceptCourse(conceptId: string): string {
  return conceptId.split("/")[0] ?? "";
}

/** Direct prerequisites of `concept` not learned yet, with their statuses from the outline. */
export function unfinishedPrereqs(outline: Outline, concept: OutlineConcept): LockedPrereq[] {
  const byId = new Map(outline.chapters.flatMap((ch) => ch.concepts).map((c) => [c.id, c]));
  return concept.prereqs
    .map((id) => byId.get(id))
    .filter((c): c is OutlineConcept => !!c && c.status !== null && c.status !== "learned")
    .map((c) => ({ id: c.id, title: c.title, status: c.status! }));
}

/** Spec 012: "Placed" for a concept learned through a placement check, "Placed · check soon"
 * while that placement is conditional; null otherwise. */
export function placedLabel(concept: {
  status: string | null;
  placed?: boolean;
  conditional?: boolean;
}): string | null {
  if (concept.status !== "learned" || !concept.placed) return null;
  return concept.conditional ? "Placed · check soon" : "Placed";
}
