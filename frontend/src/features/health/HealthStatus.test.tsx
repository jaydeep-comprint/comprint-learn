import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { HealthStatus } from "./HealthStatus";

function renderHealth() {
  // retryDelay 0 keeps the component's `retry: 1` fast in tests.
  const client = new QueryClient({ defaultOptions: { queries: { retryDelay: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <HealthStatus />
    </QueryClientProvider>,
  );
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("HealthStatus", () => {
  it("shows the loading state, then ok when API and DB are healthy", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { status: "ok", db: "ok" }));
    vi.stubGlobal("fetch", fetchMock);
    renderHealth();

    expect(screen.getByText("Checking API…")).toBeInTheDocument();
    expect(await screen.findByText("API: ok · Database: ok")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/health", expect.anything());
  });

  it("shows database unreachable on 503", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementation(() =>
          Promise.resolve(jsonResponse(503, { status: "error", db: "error" })),
        ),
    );
    renderHealth();

    expect(await screen.findByText("API: ok · Database: unreachable")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("shows API unreachable when the dev proxy answers 502 (API process down)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => Promise.resolve(new Response("", { status: 502 }))),
    );
    renderHealth();

    expect(await screen.findByText("API: unreachable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("shows API unreachable with a Retry button that refetches", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);
    renderHealth();

    const retry = await screen.findByRole("button", { name: "Retry" });
    expect(screen.getByText("API: unreachable")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2); // first try + retry: 1, then stops

    fetchMock.mockResolvedValue(jsonResponse(200, { status: "ok", db: "ok" }));
    await userEvent.click(retry);
    expect(await screen.findByText("API: ok · Database: ok")).toBeInTheDocument();
  });

  it("leaves the green state when a later refetch fails", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { status: "ok", db: "ok" }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retryDelay: 0 } } });
    render(
      <QueryClientProvider client={client}>
        <HealthStatus />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("API: ok · Database: ok")).toBeInTheDocument();

    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    await act(() => client.refetchQueries({ queryKey: ["health"] }));
    expect(await screen.findByText("API: unreachable")).toBeInTheDocument();
    expect(screen.queryByText("API: ok · Database: ok")).not.toBeInTheDocument();
  });
});
