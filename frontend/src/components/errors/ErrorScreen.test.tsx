import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "@/components/errors/ErrorBoundary";
import { RouteError } from "@/components/errors/RouteError";
import { ApiError } from "@/lib/api";

function Boom({ error }: { error: unknown }): never {
  throw error;
}

describe("error screens (spec 015)", () => {
  it("the root boundary shows Reload and the API request id as the code", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const error = new ApiError(500, "/x", "internal", "x", undefined, "ab12cd34ef56");
    render(
      <ErrorBoundary>
        <Boom error={error} />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("heading", { name: "Something went wrong" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
    expect(screen.getByText("Error code: ab12cd34")).toBeInTheDocument();
  });

  it("the route error element renders the screen (no code when Sentry is off)", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const router = createMemoryRouter([
      { path: "/", errorElement: <RouteError />, element: <Boom error={new Error("x")} /> },
    ]);
    render(<RouterProvider router={router} />);
    expect(
      await screen.findByRole("heading", { name: "Something went wrong" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Error code/)).not.toBeInTheDocument();
  });
});
