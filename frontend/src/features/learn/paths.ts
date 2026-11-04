import type { LessonStatus, LockedPrereq, Outline, OutlineConcept } from "@/lib/types";

export const STATUS_LABELS: Record<LessonStatus, string> = {
  finished: "Finished",
  in_progress: "In progress",
  ready: "Ready to start",
  locked: "Locked",
};

/** `:course` is the outline the student came from (for Back and "next up"). */
export function lessonPath(course: string, conceptId: string): string {
  return `/learn/${course}/${conceptId}`;
}

/** Unfinished direct prerequisites of `concept`, with their statuses from the outline. */
export function unfinishedPrereqs(outline: Outline, concept: OutlineConcept): LockedPrereq[] {
  const byId = new Map(outline.chapters.flatMap((ch) => ch.concepts).map((c) => [c.id, c]));
  return concept.prereqs
    .map((id) => byId.get(id))
    .filter((c): c is OutlineConcept => !!c && c.status !== null && c.status !== "finished")
    .map((c) => ({ id: c.id, title: c.title, status: c.status! }));
}
