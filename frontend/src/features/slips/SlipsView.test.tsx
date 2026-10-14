import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { slipsStore } from "@/features/slips/store";
import { createFakeSupabase, fakeSession } from "@/test/fakeSupabase";
import { jsonResponse, renderRoutes, teacherMe } from "@/test/render";

const fake = vi.hoisted(() => ({ current: null as ReturnType<typeof createFakeSupabase> | null }));
vi.mock("@/lib/supabase", () => ({
  getSupabase: () => fake.current!.client,
  getAccessToken: async () => "token-123",
  signOut: async () => {},
}));

import { SHOWN_ONCE_WARNING, SlipsView } from "@/features/slips/SlipsView";

const slips = [
  { display_name: "Aarav S.", username: "aarav42", temp_password: "tiger-maple-42" },
  { display_name: "आरव शर्मा", username: "student07", temp_password: "otter-lake-07" },
  { display_name: "Priya K.", username: "priya17", temp_password: "cloud-fern-99" },
];

const routes = [
  { path: "/classes/c1/slips", element: <SlipsView /> },
  { path: "/classes/c1", element: <p>Class page</p> },
  { path: "/classes", element: <p>Classes page</p> },
];

describe("SlipsView", () => {
  beforeEach(() => {
    fake.current = createFakeSupabase();
    fake.current.state.session = fakeSession();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, teacherMe)));
    slipsStore.clear();
  });

  it("renders one card per student with school, code, username and temp password", async () => {
    slipsStore.set({ slips, backTo: "/classes/c1", backLabel: "9A Maths" });
    renderRoutes(routes, "/classes/c1/slips");

    const cards = await screen.findAllByRole("article");
    expect(cards).toHaveLength(3);
    expect(cards[0]).toHaveTextContent("Test School");
    expect(cards[0]).toHaveTextContent("TST");
    expect(cards[0]).toHaveTextContent("aarav42");
    expect(cards[0]).toHaveTextContent("tiger-maple-42");
    expect(cards[1]).toHaveTextContent("आरव शर्मा");
    expect(cards[0]).toHaveTextContent("You'll choose your own password when you first sign in.");
    expect(screen.getByText(SHOWN_ONCE_WARNING)).toBeInTheDocument();
  });

  it("asks before leaving, in an in-app dialog", async () => {
    const confirmSpy = vi.spyOn(window, "confirm");
    slipsStore.set({ slips, backTo: "/classes/c1", backLabel: "9A Maths" });
    const { router } = renderRoutes(routes, "/classes/c1/slips");
    await screen.findAllByRole("article");

    await act(() => router.navigate("/classes"));
    expect(await screen.findByText("Leave without printing?")).toBeInTheDocument();
    expect(confirmSpy).not.toHaveBeenCalled();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Stay" }));
    expect(router.state.location.pathname).toBe("/classes/c1/slips");

    await act(() => router.navigate("/classes"));
    await user.click(await screen.findByRole("button", { name: "Leave" }));
    expect(await screen.findByText("Classes page")).toBeInTheDocument();
    expect(slipsStore.get()).toBeNull();
  });

  it("Done clears the passwords and goes back without asking", async () => {
    slipsStore.set({ slips, backTo: "/classes/c1", backLabel: "9A Maths" });
    renderRoutes(routes, "/classes/c1/slips");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Done" }));
    expect(await screen.findByText("Class page")).toBeInTheDocument();
    expect(slipsStore.get()).toBeNull();
  });

  it("shows an empty state after a reload (nothing persisted)", async () => {
    renderRoutes(routes, "/classes/c1/slips");
    expect(await screen.findByText("No slips to show")).toBeInTheDocument();
  });
});
