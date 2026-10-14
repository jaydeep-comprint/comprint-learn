import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router";

import { AuthProvider } from "@/features/auth/AuthProvider";
import type { Me } from "@/lib/types";

export function renderRoutes(routes: RouteObject[], path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, retryDelay: 0 }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>,
  );
  return { ...utils, router, queryClient };
}

export function jsonResponse(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export const teacherMe: Me = {
  id: "t1",
  display_name: "Ms Rao",
  role: "teacher",
  is_admin: false,
  username: null,
  must_change_password: false,
  org: { name: "Test School", code: "TST" },
};

export const adminMe: Me = { ...teacherMe, is_admin: true };

export const studentMe: Me = {
  ...teacherMe,
  id: "s1",
  display_name: "Aarav S.",
  role: "student",
  username: "aarav42",
};

/** A fetch mock that routes by "METHOD path" and records calls. */
export function routeFetch(handlers: Record<string, (init: RequestInit) => Response>) {
  return async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = typeof input === "string" ? input : input.toString();
    const key = `${init.method ?? "GET"} ${url}`;
    const handler = handlers[key] ?? handlers[`${init.method ?? "GET"} ${url.split("?")[0]}`];
    if (!handler) return jsonResponse(404, { code: "not_found", message: `No mock for ${key}` });
    return handler(init);
  };
}
