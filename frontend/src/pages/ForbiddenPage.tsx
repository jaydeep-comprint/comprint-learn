import { ShieldX } from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";

export function ForbiddenPage() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-4 py-16 text-center">
      <ShieldX className="size-10 text-muted-foreground" aria-hidden />
      <h1 className="text-2xl font-semibold">You don't have access to this page</h1>
      <p className="text-muted-foreground">Ask your school admin if you think you should.</p>
      <Button asChild>
        <Link to="/">Go home</Link>
      </Button>
    </div>
  );
}
