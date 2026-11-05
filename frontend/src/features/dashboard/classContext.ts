import { useOutletContext } from "react-router";

import type { SchoolClass } from "@/lib/types";

export type ClassContext = {
  cls: SchoolClass;
  /** The class course (the active course of its subject), when there is one. */
  courseSlug: string | undefined;
};

/** The class loaded by `ClassLayout`, for its tabs and the student page. */
export function useClassContext(): ClassContext {
  return useOutletContext<ClassContext>();
}
