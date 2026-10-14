import { Printer, Scissors, TriangleAlert } from "lucide-react";
import { useEffect } from "react";
import { Link, useBlocker, useNavigate } from "react-router";

import { EmptyState } from "@/components/EmptyState";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { slipsStore, useSlips } from "@/features/slips/store";
import { useMe } from "@/features/auth/useMe";
import type { Slip } from "@/lib/types";

export const SHOWN_ONCE_WARNING =
  "These passwords are shown once. Print or note them before leaving this page.";

function SlipCard({ slip, school, code }: { slip: Slip; school: string; code: string }) {
  return (
    <article className="slip flex flex-col gap-2 rounded-lg border border-dashed p-4 text-sm print:rounded-none">
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground print:text-black">
        <span className="truncate">{school}</span>
        <Scissors className="size-3 shrink-0 print:hidden" aria-hidden />
      </div>
      <p className="truncate text-base font-semibold">{slip.display_name}</p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        <dt className="text-muted-foreground print:text-black">School code</dt>
        <dd className="font-mono font-medium">{code}</dd>
        <dt className="text-muted-foreground print:text-black">Username</dt>
        <dd className="font-mono font-medium">{slip.username}</dd>
        <dt className="text-muted-foreground print:text-black">Password</dt>
        <dd className="font-mono font-medium">{slip.temp_password}</dd>
      </dl>
      <p className="mt-auto text-xs text-muted-foreground print:text-black">
        You'll choose your own password when you first sign in.
      </p>
    </article>
  );
}

/** Printable login slips for students just created or reset. In-memory only. */
export function SlipsView() {
  const batch = useSlips();
  const { data: me } = useMe();
  const navigate = useNavigate();
  // Read the store at navigation time, so "Done" (which clears it first) isn't blocked.
  const blocker = useBlocker(() => slipsStore.get() !== null);

  // Reload / closing the tab: the browser's own "leave site?" prompt.
  useEffect(() => {
    if (!batch) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [batch]);

  if (!batch || !me) {
    return (
      <EmptyState
        icon={Printer}
        title="No slips to show"
        description="Slips are shown once, right after you create students or reset a password."
        action={
          <Button asChild variant="outline">
            <Link to="/classes">Back to classes</Link>
          </Button>
        }
      />
    );
  }

  const done = () => {
    const target = batch.backTo;
    slipsStore.clear();
    navigate(target);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between print:hidden">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Login slips</h1>
          <p className="text-sm text-muted-foreground">
            {batch.slips.length} {batch.slips.length === 1 ? "student" : "students"} ·{" "}
            {batch.backLabel}
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => window.print()}>
            <Printer aria-hidden />
            Print
          </Button>
          <Button variant="outline" onClick={done}>
            Done
          </Button>
        </div>
      </div>

      <div
        role="alert"
        className="flex items-start gap-3 rounded-lg border border-warning/50 bg-warning/10 p-3 text-sm print:hidden"
      >
        <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
        <p>{SHOWN_ONCE_WARNING}</p>
      </div>

      <div className="slip-grid grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {batch.slips.map((slip) => (
          <SlipCard key={slip.username} slip={slip} school={me.org.name} code={me.org.code} />
        ))}
      </div>

      <AlertDialog open={blocker.state === "blocked"}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Leave without printing?</AlertDialogTitle>
            <AlertDialogDescription>
              These passwords won't be shown again. If you leave, you'll need to reset them.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => blocker.reset?.()}>Stay</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                slipsStore.clear();
                blocker.proceed?.();
              }}
            >
              Leave
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
