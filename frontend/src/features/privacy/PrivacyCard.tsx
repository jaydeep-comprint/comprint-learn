import { Download, ShieldCheck, ShieldOff, Trash2, Undo2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog, type ConfirmRequest } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useMe } from "@/features/auth/useMe";
import { istDate } from "@/lib/dates";
import { errorMessage } from "@/lib/errors";
import type { StudentDetail } from "@/lib/types";

import { useCancelErasure, useDownloadExport } from "./api";
import { EraseDialog, type EraseTarget } from "./EraseDialog";
import { useConsentFlow } from "./useConsentFlow";

/** Spec 014: tutor consent (any teacher); download and erasure (admins). */
export function PrivacyCard({ student }: { student: StudentDetail }) {
  const { data: me } = useMe();
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [erasing, setErasing] = useState<EraseTarget | null>(null);
  const { ask, pending } = useConsentFlow(setConfirm);
  const download = useDownloadExport();
  const cancel = useCancelErasure();
  const who = [{ id: student.student_id, display_name: student.display_name }];
  const pendingErasure = student.erase_due_at !== null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Privacy</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p>
            <span className="font-medium">AI tutor consent: </span>
            {student.tutor_consent_at ? (
              <>
                recorded {istDate(student.tutor_consent_at)}
                <span className="text-muted-foreground"> (form {student.tutor_consent_form})</span>
              </>
            ) : (
              <span className="text-muted-foreground">not recorded, so the tutor is locked</span>
            )}
          </p>
          {student.tutor_consent_at ? (
            <Button
              size="sm"
              variant="outline"
              disabled={pending}
              onClick={() => ask(who, "withdraw")}
            >
              <ShieldOff aria-hidden />
              Withdraw consent
            </Button>
          ) : (
            <Button
              size="sm"
              variant="outline"
              disabled={pending || pendingErasure}
              onClick={() => ask(who, "record")}
            >
              <ShieldCheck aria-hidden />
              Record consent
            </Button>
          )}
        </div>

        {me?.is_admin && (
          <div className="flex flex-wrap items-center gap-2 border-t pt-4">
            <Button
              size="sm"
              variant="outline"
              disabled={download.isPending}
              onClick={() =>
                download.mutate(
                  { id: student.student_id, username: student.username },
                  { onError: (err) => toast.error(errorMessage(err)) },
                )
              }
            >
              <Download aria-hidden />
              Download data (JSON)
            </Button>
            {pendingErasure && student.erase_due_at ? (
              <>
                <span className="text-destructive" title="Runs nightly">
                  Erasure scheduled for {istDate(student.erase_due_at)}
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={cancel.isPending}
                  onClick={() =>
                    cancel.mutate(student.student_id, {
                      onSuccess: () =>
                        toast.success(
                          `Erasure cancelled. ${student.display_name} stays deactivated until you reactivate them.`,
                        ),
                      onError: (err) => toast.error(errorMessage(err)),
                    })
                  }
                >
                  <Undo2 aria-hidden />
                  Cancel erasure
                </Button>
              </>
            ) : (
              <Button
                size="sm"
                variant="destructive"
                onClick={() =>
                  setErasing({
                    id: student.student_id,
                    display_name: student.display_name,
                    username: student.username,
                  })
                }
              >
                <Trash2 aria-hidden />
                Erase student…
              </Button>
            )}
          </div>
        )}
      </CardContent>
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
      <EraseDialog student={erasing} onClose={() => setErasing(null)} />
    </Card>
  );
}
