import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mermaid = vi.hoisted(() => ({
  initialize: vi.fn(),
  render: vi.fn(async (_id: string, source: string) => ({
    svg: `<svg data-src="${source}"></svg>`,
  })),
}));
vi.mock("mermaid", () => ({ default: mermaid }));

import { Markdown } from "@/components/markdown/Markdown";
import { rewriteImageSrc } from "@/components/markdown/rewriteImageSrc";

const BASE = "/content-assets/physics-9-10/01-motion/distance-and-displacement/";

describe("Markdown", () => {
  it("renders inline and display maths with KaTeX (MathML kept)", () => {
    const { container } = render(
      <Markdown>{"Solve $2x = 4$.\n\n$$\nx = \\frac{4}{2}\n$$"}</Markdown>,
    );
    expect(container.querySelectorAll(".katex")).toHaveLength(2);
    expect(container.querySelector(".katex-display")).not.toBeNull();
    expect(container.querySelector("math")).not.toBeNull();
  });

  it("rewrites content images to the asset base and drops other sources", () => {
    render(
      <Markdown assetBase={BASE}>
        {"![Path](img/path.svg)\n\n![Remote](https://evil.example/x.png)\n\n![Up](img/../x.svg)"}
      </Markdown>,
    );
    const imgs = screen.getAllByRole("img");
    expect(imgs).toHaveLength(1);
    expect(imgs[0]).toHaveAttribute("src", `${BASE}img/path.svg`);
    expect(imgs[0]).toHaveAttribute("alt", "Path");
    expect(imgs[0]).toHaveAttribute("loading", "lazy");
  });

  it("renders no images without an asset base", () => {
    render(<Markdown>{"![Path](img/path.svg)"}</Markdown>);
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("never renders raw HTML", () => {
    const { container } = render(
      <Markdown>{'Hi <script>alert(1)</script><b onclick="x()">bold</b>'}</Markdown>,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
  });

  it("opens links in a new tab safely", () => {
    render(<Markdown>{"[Video](https://www.youtube.com/watch?v=abc)"}</Markdown>);
    const link = screen.getByRole("link", { name: "Video" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("renders a mermaid fence through the lazily loaded module", async () => {
    render(<Markdown>{"```mermaid\ngraph LR; A-->B\n```"}</Markdown>);
    await waitFor(() => expect(mermaid.render).toHaveBeenCalled());
    expect(mermaid.initialize).toHaveBeenCalledWith(
      expect.objectContaining({ securityLevel: "strict" }),
    );
    await waitFor(() => expect(screen.getByTestId("mermaid").querySelector("svg")).not.toBeNull());
  });

  it("falls back to the source when mermaid fails", async () => {
    mermaid.render.mockRejectedValueOnce(new Error("parse error"));
    render(<Markdown>{"```mermaid\nnot a diagram\n```"}</Markdown>);
    expect(await screen.findByText("Diagram couldn't be shown")).toBeInTheDocument();
    expect(screen.getByText("not a diagram")).toBeInTheDocument();
  });
});

describe("rewriteImageSrc", () => {
  it("accepts only img/ paths", () => {
    expect(rewriteImageSrc("img/a/b.png", "/x/")).toBe("/x/img/a/b.png");
    expect(rewriteImageSrc("/img/a.png", "/x/")).toBeNull();
    expect(rewriteImageSrc("img/.hidden.png", "/x/")).toBeNull();
    expect(rewriteImageSrc("data:image/png;base64,xx", "/x/")).toBeNull();
    expect(rewriteImageSrc("javascript:alert(1)", "/x/")).toBeNull();
  });
});
