import { toast } from "sonner";

import type { XpAward } from "@/lib/types";

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

/** Tests only. */
export function resetShownAwards(): void {
  shown.clear();
}
