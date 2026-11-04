import { ComeBackLater } from "@/features/learn/FailedScreen";
import type { RemediationRef } from "@/lib/types";

/** Shown on a lesson whose next part failed and isn't open yet. The worked examples stay
 * readable through the step indicator. */
export function WaitingPanel(props: {
  course: string;
  kpTitle: string;
  remediations: RemediationRef[];
  exclude: string;
}) {
  return <ComeBackLater {...props} heading="This part reopens later" />;
}
