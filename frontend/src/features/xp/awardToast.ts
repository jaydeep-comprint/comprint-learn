import { toast } from "sonner";

import type { QuizXp, XpAward } from "@/lib/types";

/** Toast copy for an award (spec 008). */
export function awardMessage(xp: XpAward): string {
  const hints = xp.hints > 0 ? " · hints used" : "";
  switch (xp.grade) {
    case "perfect":
      return `+${xp.amount} XP · Perfect ×1.2${hints}`;
    case "passed":
      return `+${xp.amount} XP${hints}`;
    case "partial":
      return `+${xp.amount} XP · Partly right${hints}`;
    case "poor":
      return `No XP this time${hints}`;
    case "rushed":
      return `−${Math.abs(xp.amount)} XP · Answers were too fast to be real tries`;
  }
}

const shown = new Set<string>();

/** Shows the award once per session: a resent or already-answered result carries the same
 *  event, so it's deduped by session id. Returns whether a toast was shown. */
export function showAwardToast(xp: XpAward, sessionId: string | null | undefined): boolean {
  const key = sessionId ?? "";
  if (!key || shown.has(key)) return false;
  shown.add(key);
  const message = awardMessage(xp);
  const description = xp.goal_met_today ? "Daily goal met 🎉" : undefined;
  if (xp.amount < 0) toast.warning(message, { description });
  else toast.success(message, { description });
  return true;
}

/** Spec 007: a quiz's XP (the total of its per-subject awards), once per quiz. */
export function quizAwardMessage(xp: QuizXp): string {
  if (xp.amount > 0) return `+${xp.amount} XP · Quiz`;
  if (xp.amount < 0) return `−${Math.abs(xp.amount)} XP · Answers were too fast to be real tries`;
  return "No XP from this quiz";
}

export function showQuizAwardToast(xp: QuizXp, quizId: string): boolean {
  const key = `quiz:${quizId}`;
  if (shown.has(key)) return false;
  shown.add(key);
  const description = xp.goal_met_today ? "Daily goal met 🎉" : undefined;
  if (xp.amount < 0) toast.warning(quizAwardMessage(xp), { description });
  else toast.success(quizAwardMessage(xp), { description });
  return true;
}

/** Tests only. */
export function resetShownAwards(): void {
  shown.clear();
}
