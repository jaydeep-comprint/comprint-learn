import { Printer, ShieldCheck, ShieldOff } from "lucide-react";
import { Link } from "react-router";

import type { ConfirmRequest } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { istDate } from "@/lib/dates";
import type { PrivacyFields } from "@/lib/types";

import { MAX_CONSENT_SELECTION } from "./api";
import { plural, useConsentFlow } from "./useConsentFlow";

/** "Recorded 12 Nov 2026" (form version on hover) or "Not recorded". */
export function ConsentStatus({ student }: { student: PrivacyFields }) {
  if (!student.tutor_consent_at) {
    return <span className="text-muted-foreground">Not recorded</span>;
  }
  return (
    <span title={`Form version ${student.tutor_consent_form ?? ""}`}>
      Recorded {istDate(student.tutor_consent_at)}
    </span>
  );
}

/** "Erasure after 18 Nov 2026" for a student with a pending erasure. */
export function ErasureBadge({ dueAt }: { dueAt: string }) {
  return (
    <span
      title="Runs nightly"
      className="ml-2 inline-flex rounded-md border border-destructive/40 px-1.5 py-0.5 align-middle text-xs text-destructive"
    >
      Erasure after {istDate(dueAt)}
    </span>
  );
}

type Who = { id: string; display_name: string };

/** The bar above a roster while students are selected. */
export function ConsentBulkBar({
  selected,
  onClear,
  confirm,
  printTo,
}: {
  selected: Who[];
  onClear: () => void;
  confirm: (r: ConfirmRequest) => void;
  /** Spec 014: the class print view (class Students tab only). */
  printTo?: string;
}) {
  const { ask, pending } = useConsentFlow(confirm);
  const n = selected.length;
  const tooMany = n > MAX_CONSENT_SELECTION;
  if (n === 0) return null;
  return (
    <div
      role="region"
      aria-label="Selected students"
      className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/40 px-3 py-2 text-sm"
    >
      <span className="font-medium">{plural(n)} selected</span>
      <Button
        size="sm"
        variant="outline"
        disabled={pending || tooMany}
        onClick={() => ask(selected, "record", onClear)}
      >
        <ShieldCheck aria-hidden />
        Record consent
      </Button>
      <Button
        size="sm"
        variant="outline"
        disabled={pending || tooMany}
        onClick={() => ask(selected, "withdraw", onClear)}
      >
        <ShieldOff aria-hidden />
        Withdraw consent
      </Button>
      {printTo && (
        <Button size="sm" variant="outline" asChild>
          <Link to={`${printTo}?students=${selected.map((s) => s.id).join(",")}`}>
            <Printer aria-hidden />
            Print consent forms
          </Link>
        </Button>
      )}
      <Button size="sm" variant="ghost" onClick={onClear}>
        Clear
      </Button>
      {tooMany && (
        <p className="w-full text-xs text-destructive">
          Select at most {MAX_CONSENT_SELECTION} students at a time.
        </p>
      )}
    </div>
  );
}
