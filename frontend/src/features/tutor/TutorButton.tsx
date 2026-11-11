import { Lock, MessageCircleQuestion } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useTutorThread } from "@/features/tutor/api";

/** Spec 014: shown under a disabled tutor button when no consent form is recorded. */
export const TUTOR_CONSENT_NOTE =
  "The AI tutor needs a consent form from your parent or guardian. Ask your teacher.";

/** "Get help · N hints left" next to the answer controls; hidden when the tutor is off, and
 * disabled with a note when the student has no tutor consent (spec 014). */
export function TutorButton({
  sessionId,
  position,
  onOpen,
}: {
  sessionId: string;
  position: number;
  onOpen: () => void;
}) {
  const { data: thread } = useTutorThread(sessionId, position);
  if (!thread?.enabled) return null;
  if (!thread.consent) {
    return (
      <div className="w-full space-y-1 sm:w-auto">
        <Button variant="outline" disabled className="w-full sm:w-auto">
          <Lock aria-hidden />
          Get help
        </Button>
        <p className="max-w-xs text-xs text-muted-foreground">{TUTOR_CONSENT_NOTE}</p>
      </div>
    );
  }
  const label =
    thread.mode === "after"
      ? "Ask why · no XP cost"
      : thread.hints_left > 0
        ? `Get help · ${thread.hints_left} hint${thread.hints_left === 1 ? "" : "s"} left`
        : "Get help";
  return (
    <Button variant="outline" onClick={onOpen} className="w-full sm:w-auto">
      <MessageCircleQuestion aria-hidden />
      {label}
    </Button>
  );
}
