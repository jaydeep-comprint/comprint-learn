import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";

import type { XpSummary } from "@/lib/types";

/** Renders `element` at `path` with a fresh QueryClient (no AuthProvider: supabase is mocked). */
export function renderAt(element: ReactNode, path = "/", pattern = "/") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const router = createMemoryRouter([{ path: pattern, element }], { initialEntries: [path] });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { router, queryClient };
}

export function summary(overrides: Partial<XpSummary> = {}): XpSummary {
  return {
    today: [{ subject: "maths", xp: 12, goal: 15, met: false }],
    streak: { days: 4, today_met: false },
    week_xp: 84,
    total_xp: 300,
    goals: [{ subject: "maths", class_goal: 15, own_goal: null, effective: 15 }],
    leaderboards: [],
    ...overrides,
  };
}
