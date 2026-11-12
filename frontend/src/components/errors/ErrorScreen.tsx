import { TriangleAlert } from "lucide-react";

import { shortCode } from "@/components/errors/codes";
import { Button } from "@/components/ui/button";

/** Spec 015: the full-page "Something went wrong" screen (works signed out and on phones). */
export function ErrorScreen({ code }: { code?: string | null }) {
  const short = shortCode(code);
  return (
    <div
      role="alert"
      className="mx-auto flex min-h-[60vh] max-w-md flex-col items-center justify-center gap-4 px-4 py-16 text-center"
    >
      <TriangleAlert className="size-10 text-muted-foreground" aria-hidden />
      <h1 className="text-2xl font-semibold">Something went wrong</h1>
      <p className="text-muted-foreground">
        Reload the page to try again. If it keeps happening, tell your teacher the code below.
      </p>
      <Button onClick={() => window.location.reload()}>Reload</Button>
      {short && <p className="text-xs text-muted-foreground">Error code: {short}</p>}
    </div>
  );
}
