import { Badge } from "@/components/ui/badge";
import type { UserStatus } from "@/lib/types";

const LABELS: Record<UserStatus, string> = {
  invited: "Invited",
  active: "Active",
  deactivated: "Deactivated",
};

export function StatusBadge({ status }: { status: UserStatus }) {
  return (
    <Badge variant={status === "active" ? "secondary" : "outline"} className="font-normal">
      {LABELS[status]}
    </Badge>
  );
}
