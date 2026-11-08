import { ExternalLink } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { useMediaQuery } from "@/lib/useMediaQuery";
import type { SummaryFact } from "@/lib/types";

/** A small numbered chip `[2]`: the fact behind a sentence and a link to where it came from.
 * A popover on desktop, a bottom sheet on phones (spec 011). */
export function CitationChip({
  n,
  fact,
  href,
}: {
  n: number;
  fact: SummaryFact;
  href: string | null;
}) {
  const desktop = useMediaQuery("(min-width: 768px)");
  const [open, setOpen] = useState(false);
  const chip = (
    <button
      type="button"
      className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded border bg-muted px-1 align-baseline text-xs font-medium tabular-nums hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      aria-label={`Source ${n}`}
      onClick={desktop ? undefined : () => setOpen(true)}
    >
      {n}
    </button>
  );
  const body = (
    <div className="space-y-3 text-sm">
      <p>{fact.text}</p>
      {href ? (
        <Button asChild size="sm" variant="outline">
          <Link to={href} onClick={() => setOpen(false)}>
            Open
            <ExternalLink className="size-3.5" aria-hidden />
          </Link>
        </Button>
      ) : (
        <p className="text-muted-foreground">This source is no longer available.</p>
      )}
    </div>
  );
  if (desktop) {
    return (
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>{chip}</PopoverTrigger>
        <PopoverContent align="start">{body}</PopoverContent>
      </Popover>
    );
  }
  return (
    <>
      {chip}
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="bottom" className="p-4 pb-6">
          <SheetTitle className="pr-8">Source {n}</SheetTitle>
          <SheetDescription className="sr-only">
            The dashboard fact behind this sentence
          </SheetDescription>
          {body}
        </SheetContent>
      </Sheet>
    </>
  );
}

/** A claim's text followed by its citation chips. */
export function ClaimText({
  text,
  citations,
  facts,
  hrefFor,
}: {
  text: string;
  citations: string[];
  facts: SummaryFact[];
  hrefFor: (fact: SummaryFact) => string | null;
}) {
  return (
    <>
      {text}{" "}
      {citations.map((id) => {
        const i = facts.findIndex((f) => f.id === id);
        if (i < 0) return null;
        const fact = facts[i]!;
        return <CitationChip key={id} n={i + 1} fact={fact} href={hrefFor(fact)} />;
      })}
    </>
  );
}
