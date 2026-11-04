import ReactMarkdown, { type Components, type ExtraProps } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { Mermaid } from "@/components/markdown/Mermaid";
import { rewriteImageSrc } from "@/components/markdown/rewriteImageSrc";
import { cn } from "@/lib/utils";

/** The text of a ```mermaid fence, if `pre` is one. */
function mermaidSource(node: ExtraProps["node"]): string | null {
  const code = node?.children[0];
  if (!code || code.type !== "element" || code.tagName !== "code") return null;
  const classes = code.properties.className;
  if (!Array.isArray(classes) || !classes.includes("language-mermaid")) return null;
  return code.children.map((c) => (c.type === "text" ? c.value : "")).join("");
}

/**
 * Content Markdown: GitHub-style, `$…$` / `$$…$$` maths (KaTeX, MathML kept for screen readers),
 * content images, and ```mermaid diagrams. Raw HTML is never rendered (no rehype-raw).
 */
export function Markdown({
  children,
  assetBase = "",
  className,
}: {
  children: string;
  assetBase?: string;
  className?: string;
}) {
  const components: Components = {
    img: ({ src, alt }) => {
      const url = rewriteImageSrc(typeof src === "string" ? src : null, assetBase);
      if (!url) return null;
      return <img src={url} alt={alt ?? ""} loading="lazy" className="my-4 h-auto max-w-full" />;
    },
    a: ({ href, children: text }) => (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="font-medium text-primary underline underline-offset-4"
      >
        {text}
      </a>
    ),
    pre: ({ node, children: inner }) => {
      const source = mermaidSource(node);
      if (source !== null) return <Mermaid source={source} />;
      return <pre className="my-4 overflow-x-auto rounded-md bg-muted p-3 text-sm">{inner}</pre>;
    },
  };
  return (
    <div className={cn("markdown", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={components}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
