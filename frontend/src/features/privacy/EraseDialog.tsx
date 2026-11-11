import { useState } from "react";
import { toast } from "sonner";

import { FormError } from "@/components/FormError";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/errors";

import { useRequestErasure } from "./api";

export type EraseTarget = { id: string; display_name: string; username: string };

/** Spec 014: type the username to schedule an erasure. Stays open while the request runs. */
export function EraseDialog({
  student,
  onClose,
}: {
  student: EraseTarget | null;
  onClose: () => void;
}) {
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);
  const erase = useRequestErasure();
  const matches = student !== null && typed.trim().toLowerCase() === student.username.toLowerCase();

  const close = () => {
    if (erase.isPending) return;
    setTyped("");
    setError(null);
    onClose();
  };

  const submit = () => {
    if (!student || !matches) return;
    setError(null);
    erase.mutate(
      { id: student.id, confirmUsername: typed.trim() },
      {
        onSuccess: () => {
          toast.success(`Erasure of ${student.display_name} scheduled`);
          setTyped("");
          onClose();
        },
        onError: (err) => setError(errorMessage(err)),
      },
    );
  };

  return (
    <AlertDialog open={student !== null} onOpenChange={(open) => !open && close()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Erase {student?.display_name}?</AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div className="space-y-2">
              <p>
                They are signed out and can&apos;t sign in from now on. In 7 days their name and
                username are removed and their tutor chats are deleted. Their learning records stay
                without a name, so class statistics don&apos;t change.
              </p>
              <p>You can cancel during those 7 days. After that it can&apos;t be undone.</p>
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <Label htmlFor="erase-username">
            Type <span className="font-mono">{student?.username}</span> to confirm
          </Label>
          <Input
            id="erase-username"
            autoComplete="off"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
          />
          <FormError message={error} />
          <AlertDialogFooter>
            <AlertDialogCancel type="button" disabled={erase.isPending}>
              Cancel
            </AlertDialogCancel>
            <Button type="submit" variant="destructive" disabled={!matches || erase.isPending}>
              {erase.isPending ? "Scheduling…" : "Erase student"}
            </Button>
          </AlertDialogFooter>
        </form>
      </AlertDialogContent>
    </AlertDialog>
  );
}
