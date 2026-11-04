import { Navigate } from "react-router";

import { useMe } from "@/features/auth/useMe";
import { StudentHome } from "@/features/learn/StudentHome";

/** Students see their courses. Staff land on their classes. */
export function HomePage() {
  const { data: me } = useMe();
  if (!me) return null;
  if (me.role === "teacher") return <Navigate to="/classes" replace />;
  const firstName = me.display_name.trim().split(/\s+/)[0] ?? "";
  return <StudentHome firstName={firstName} />;
}
