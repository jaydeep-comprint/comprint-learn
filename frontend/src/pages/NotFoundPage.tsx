import { SearchX } from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";

export function NotFoundPage() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-4 px-4 py-16 text-center">
      <SearchX className="size-10 text-muted-foreground" aria-hidden />
      <h1 className="text-2xl font-semibold">Not found</h1>
      <p className="text-muted-foreground">This page doesn't exist, or you can't see it.</p>
      <Button asChild>
        <Link to="/">Go home</Link>
      </Button>
    </div>
  );
}
