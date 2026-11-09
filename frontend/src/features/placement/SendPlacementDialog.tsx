import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { FormError } from "@/components/FormError";
import { StudentPicker } from "@/components/StudentPicker";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useClassStudents } from "@/features/classes/api";
import { errorMessage } from "@/lib/errors";

import { useSendPlacement } from "./api";
import { sentMessage } from "./status";

function SendForm({ classId, onClose }: { classId: string; onClose: () => void }) {
  const students = useClassStudents(classId);
  const send = useSendPlacement(classId);
  const [whole, setWhole] = useState(true);
  const [chosen, setChosen] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!whole && chosen.length === 0) {
      setError("Choose at least one student.");
      return;
    }
    setError(null);
    try {
      const out = await send.mutateAsync(whole ? null : chosen);
      toast.success(sentMessage(out.sent, out.skipped));
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Send placement check</DialogTitle>
        <DialogDescription>
          Students take a short check (up to 25 questions, no timer, no XP) and skip what they
          already know. Anyone who already has one is skipped.
        </DialogDescription>
      </DialogHeader>
      <StudentPicker
        name="placement-audience"
        students={students.data ?? []}
        whole={whole}
        onWholeChange={setWhole}
        chosen={chosen}
        onChosenChange={setChosen}
      />
      <FormError message={error} />
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={() => void submit()} disabled={send.isPending}>
          {send.isPending && <Loader2 className="animate-spin" aria-hidden />}
          Send
        </Button>
      </DialogFooter>
    </>
  );
}

export function SendPlacementDialog({
  classId,
  open,
  onClose,
}: {
  classId: string;
  open: boolean;
  onClose: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        {open && <SendForm classId={classId} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  );
}
