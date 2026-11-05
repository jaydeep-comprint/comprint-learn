import { MessageCircleQuestion } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useTutorThread } from "@/features/tutor/api";

/** "Get help · N hints left" next to the answer controls; hidden when the tutor is off. */
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
