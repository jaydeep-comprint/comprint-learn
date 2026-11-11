import { ShieldCheck, ShieldOff } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog, type ConfirmRequest } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { istDate } from "@/lib/dates";
import type { StudentDetail } from "@/lib/types";

import { useConsentFlow } from "./useConsentFlow";

/** Spec 014: the student's tutor consent (any teacher). */
export function PrivacyCard({ student }: { student: StudentDetail }) {
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const { ask, pending } = useConsentFlow(setConfirm);
  const who = [{ id: student.student_id, display_name: student.display_name }];
  const pendingErasure = student.erase_due_at !== null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Privacy</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
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
      </CardContent>
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </Card>
  );
}
