import type { AssignmentStatus } from "@/lib/types";

export const ASSIGNMENT_STATUS: Record<AssignmentStatus, string> = {
  done_on_time: "Done on time",
  done_late: "Done late",
  done_early: "Already learned",
  overdue: "Overdue",
  in_progress: "In progress",
  not_started: "Not started",
};
