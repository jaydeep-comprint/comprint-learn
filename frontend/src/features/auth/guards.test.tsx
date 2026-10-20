import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Me } from "@/lib/types";
import { createFakeSupabase, fakeSession } from "@/test/fakeSupabase";
import { adminMe, jsonResponse, renderRoutes, studentMe, teacherMe } from "@/test/render";

const fake = vi.hoisted(() => ({ current: null as ReturnType<typeof createFakeSupabase> | null }));
vi.mock("@/lib/supabase", () => ({
  getSupabase: () => fake.current!.client,
  getAccessToken: async () => fake.current!.state.session?.access_token ?? null,
  signOut: async () => {},
}));

import { RequireAuth, RequireRole } from "@/features/auth/guards";

const routes = [
  { path: "/login", element: <p>Login page</p> },
  {
    element: <RequireAuth />,
    children: [
      { path: "/change-password", element: <p>Change password page</p> },
      { path: "/", element: <p>Home page</p> },
      {
        element: <RequireRole access="staff" />,
        children: [{ path: "/classes", element: <p>Classes page</p> }],
      },
      {
        element: <RequireRole access="admin" />,
        children: [{ path: "/teachers", element: <p>Teachers page</p> }],
      },
    ],
  },
];

function signedInAs(me: Me) {
  fake.current!.state.session = fakeSession();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, me)));
}

describe("route guards", () => {
  beforeEach(() => {
    fake.current = createFakeSupabase();
  });

  it("sends signed-out users to /login", async () => {
    renderRoutes(routes, "/classes");
    expect(await screen.findByText("Login page")).toBeInTheDocument();
  });

  it("lets a teacher into staff pages", async () => {
    signedInAs(teacherMe);
    renderRoutes(routes, "/classes");
    expect(await screen.findByText("Classes page")).toBeInTheDocument();
  });

  it("shows 403 to a student on a staff page", async () => {
    signedInAs(studentMe);
    renderRoutes(routes, "/classes");
    expect(await screen.findByText("You don't have access to this page")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go home" })).toHaveAttribute("href", "/");
  });

  it("shows 403 to a non-admin teacher on an admin page, and lets an admin in", async () => {
    signedInAs(teacherMe);
    const first = renderRoutes(routes, "/teachers");
    expect(await screen.findByText("You don't have access to this page")).toBeInTheDocument();
    first.unmount();

    signedInAs(adminMe);
    renderRoutes(routes, "/teachers");
    expect(await screen.findByText("Teachers page")).toBeInTheDocument();
  });

  it("forces a temp-password student to /change-password", async () => {
    signedInAs({ ...studentMe, must_change_password: true });
    const { router } = renderRoutes(routes, "/");
    expect(await screen.findByText("Change password page")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/change-password");
  });
});
