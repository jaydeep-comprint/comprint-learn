import type { AtRiskCode } from "@/lib/types";

/** Short names for the at-risk rules (spec 010); the API's `detail` carries the numbers. */
export const AT_RISK_LABELS: Record<AtRiskCode, string> = {
  kp_fail_rate: "Failing many KP tries",
  negative_xp: "Lost XP for rushing",
  low_xp_rate: "Little XP for the time spent",
  falling_memory: "Weak memory of key concepts",
  overdue_assignment: "Overdue assignment",
  inactive: "No activity for 7 days",
};
