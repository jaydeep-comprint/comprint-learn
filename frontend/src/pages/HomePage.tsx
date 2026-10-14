import { BookOpen } from "lucide-react";
import { Navigate } from "react-router";

import { useMe } from "@/features/auth/useMe";

/** Students: a stub until spec 004. Staff land on their classes. */
export function HomePage() {
  const { data: me } = useMe();
  if (!me) return null;
  if (me.role === "teacher") return <Navigate to="/classes" replace />;

  const firstName = me.display_name.trim().split(/\s+/)[0];
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="text-2xl font-semibold sm:text-3xl">Hi {firstName}</h1>
      <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed p-10 text-center">
        <BookOpen className="size-8 text-muted-foreground" aria-hidden />
        <p className="text-muted-foreground">Your courses will appear here soon.</p>
      </div>
    </div>
  );
}
