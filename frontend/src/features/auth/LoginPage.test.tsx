import { AuthApiError } from "@supabase/supabase-js";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createFakeSupabase } from "@/test/fakeSupabase";
import { jsonResponse, renderRoutes } from "@/test/render";

const fake = vi.hoisted(() => ({ current: null as ReturnType<typeof createFakeSupabase> | null }));
vi.mock("@/lib/supabase", () => ({
  getSupabase: () => fake.current!.client,
  getAccessToken: async () => fake.current!.state.session?.access_token ?? null,
  signOut: async () => {
    await fake.current!.auth.signOut();
  },
}));

import { LoginPage } from "@/features/auth/LoginPage";

const routes = [
  { path: "/login", element: <LoginPage /> },
  { path: "/", element: <p>Home page</p> },
];

describe("LoginPage", () => {
  beforeEach(() => {
    fake.current = createFakeSupabase();
    localStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(200, { status: "ok", db: "ok" })),
    );
  });

  it("signs a student in with a synthetic email and remembers the school code", async () => {
    const user = userEvent.setup();
    renderRoutes(routes, "/login");
    await user.type(await screen.findByLabelText("School code"), " dps-rkp ");
    await user.type(screen.getByLabelText("Username"), "Aarav42");
    await user.type(screen.getByLabelText("Password"), "tiger-maple-42");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Home page")).toBeInTheDocument();
    expect(fake.current!.auth.signInWithPassword).toHaveBeenCalledWith({
      email: "aarav42@dps-rkp.students.invalid",
      password: "tiger-maple-42",
    });
    expect(localStorage.getItem("schoolCode")).toBe("DPS-RKP");
  });

  it("pre-fills the remembered school code", async () => {
    localStorage.setItem("schoolCode", "TST");
    renderRoutes(routes, "/login");
    expect(await screen.findByLabelText("School code")).toHaveValue("TST");
  });

  it("shows one message for wrong student credentials", async () => {
    fake.current!.auth.signInWithPassword.mockResolvedValueOnce({
      data: { session: null },
      error: new AuthApiError("Invalid login credentials", 400, "invalid_credentials"),
    } as never);
    const user = userEvent.setup();
    renderRoutes(routes, "/login");
    await user.type(await screen.findByLabelText("School code"), "TST");
    await user.type(screen.getByLabelText("Username"), "nobody");
    await user.type(screen.getByLabelText("Password"), "wrong-pass");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Incorrect school code, username or password.",
    );
    expect(localStorage.getItem("schoolCode")).toBeNull();
  });

  it("signs staff in with email on the Staff tab", async () => {
    const user = userEvent.setup();
    renderRoutes(routes, "/login");
    await user.click(await screen.findByRole("tab", { name: "Staff" }));
    await user.type(screen.getByLabelText("Email"), "rao@school.in");
    await user.type(screen.getByLabelText("Password"), "secret-pass");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() =>
      expect(fake.current!.auth.signInWithPassword).toHaveBeenCalledWith({
        email: "rao@school.in",
        password: "secret-pass",
      }),
    );
    expect(await screen.findByText("Home page")).toBeInTheDocument();
  });

  it("explains when the sign-in service can't be reached", async () => {
    fake.current!.auth.signInWithPassword.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const user = userEvent.setup();
    renderRoutes(routes, "/login");
    await user.type(await screen.findByLabelText("School code"), "TST");
    await user.type(screen.getByLabelText("Username"), "a");
    await user.type(screen.getByLabelText("Password"), "b");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Can't reach the sign-in service. Try again in a minute.",
    );
  });

  it("shows the API health line in the footer", async () => {
    renderRoutes(routes, "/login");
    expect(await screen.findByText("API: ok · Database: ok")).toBeInTheDocument();
  });
});
