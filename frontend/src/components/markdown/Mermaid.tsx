import { useEffect, useId, useRef, useState } from "react";

/**
 * A ```mermaid fence rendered as a diagram. The mermaid library is a separate chunk, loaded only
 * when a page has a diagram. On a load or parse error the source is shown instead.
 */
export function Mermaid({ source }: { source: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  const id = `mermaid-${useId().replace(/[^a-zA-Z0-9-]/g, "")}`;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { default: mermaid } = await import("mermaid");
        mermaid.initialize({ startOnLoad: false, securityLevel: "strict" });
        const { svg } = await mermaid.render(id, source);
        if (!cancelled && ref.current) ref.current.innerHTML = svg;
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, source]);

  if (failed) {
    return (
      <figure className="my-4">
        <pre className="overflow-x-auto rounded-md bg-muted p-3 text-sm">{source}</pre>
        <figcaption className="mt-1 text-sm text-muted-foreground">
          Diagram couldn&apos;t be shown
        </figcaption>
      </figure>
    );
  }
  return (
    <div
      ref={ref}
      className="my-4 flex justify-center overflow-x-auto [&_svg]:h-auto [&_svg]:max-w-full"
      data-testid="mermaid"
    />
  );
}
