import type { ConfirmRequest } from "@/components/ConfirmDialog";
import { toast } from "sonner";

import { errorMessage } from "@/lib/errors";

import { type ConsentAction, useNotice, useSetConsent } from "./api";

export type Who = { id: string; display_name: string };

export function plural(n: number) {
  return n === 1 ? "1 student" : `${n} students`;
}

/** Record / withdraw with the spec's confirmation wording and toasts. */
export function useConsentFlow(confirm: (r: ConfirmRequest) => void) {
  const notice = useNotice();
  const setConsent = useSetConsent();
  const ask = (students: Who[], action: ConsentAction, onDone?: () => void) => {
    const n = students.length;
    const who = n === 1 ? (students[0]?.display_name ?? plural(1)) : plural(n);
    const run = () =>
      setConsent.mutate(
        { ids: students.map((s) => s.id), action },
        {
          onSuccess: () => {
            toast.success(
              action === "record" ? `Consent recorded for ${who}` : `Consent withdrawn for ${who}`,
            );
            onDone?.();
          },
          onError: (err) => toast.error(errorMessage(err)),
        },
      );
    confirm(
      action === "record"
        ? {
            title: `Record tutor consent for ${who}?`,
            description: `I confirm the school holds a signed consent form (version ${
              notice.data?.version ?? ""
            }) from a parent or guardian of each selected student.`,
            confirmLabel: "Record consent",
            onConfirm: run,
          }
        : {
            title: `Withdraw tutor consent for ${who}?`,
            description:
              "The AI tutor will be locked for these students and their tutor chat text will be deleted now. This can't be undone.",
            confirmLabel: "Withdraw consent",
            destructive: true,
            onConfirm: run,
          },
    );
  };
  // Recording names the form version, so it waits for the notice.
  return { ask, pending: setConsent.isPending || !notice.data };
}
