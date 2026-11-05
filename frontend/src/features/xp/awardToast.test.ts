import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { XpAward } from "@/lib/types";

import { awardMessage, resetShownAwards, showAwardToast } from "./awardToast";

function award(overrides: Partial<XpAward> = {}): XpAward {
  return {
    amount: 5,
    grade: "passed",
    base_minutes: "5.0",
    hints: 0,
    goal_met_today: false,
    ...overrides,
  };
}

describe("awardMessage", () => {
  it.each([
    [award({ amount: 6, grade: "perfect" }), "+6 XP · Perfect ×1.2"],
    [award({ amount: 5, grade: "passed" }), "+5 XP"],
    [award({ amount: 1, grade: "partial" }), "+1 XP · Partly right"],
    [award({ amount: 0, grade: "poor" }), "No XP this time"],
    [award({ amount: -1, grade: "rushed" }), "−1 XP · Answers were too fast to be real tries"],
    [award({ amount: 3, grade: "passed", hints: 1 }), "+3 XP · hints used"],
  ])("%o → %s", (xp, text) => {
    expect(awardMessage(xp)).toBe(text);
  });
});

describe("showAwardToast", () => {
  beforeEach(() => resetShownAwards());

  it("shows once per session and announces the goal", () => {
    const success = vi.spyOn(toast, "success").mockReturnValue(1);
    expect(showAwardToast(award({ goal_met_today: true }), "s1")).toBe(true);
    expect(success).toHaveBeenCalledWith("+5 XP", { description: "Daily goal met 🎉" });
    expect(showAwardToast(award({ goal_met_today: true }), "s1")).toBe(false); // a resend
    expect(success).toHaveBeenCalledTimes(1);
  });

  it("warns for a penalty and needs a session id", () => {
    const warning = vi.spyOn(toast, "warning").mockReturnValue(1);
    expect(showAwardToast(award({ amount: -1, grade: "rushed" }), null)).toBe(false);
    expect(showAwardToast(award({ amount: -1, grade: "rushed" }), "s2")).toBe(true);
    expect(warning).toHaveBeenCalledWith("−1 XP · Answers were too fast to be real tries", {
      description: undefined,
    });
  });
});
