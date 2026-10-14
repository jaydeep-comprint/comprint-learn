import { beforeEach, describe, expect, it, vi } from "vitest";

const supabase = vi.hoisted(() => ({
  getAccessToken: vi.fn(async () => "token-123" as string | null),
  signOut: vi.fn(async () => {}),
  getSupabase: vi.fn(),
}));
vi.mock("@/lib/supabase", () => supabase);

import { ApiError, apiFetch, redirect } from "@/lib/api";

function respond(status: number, body?: unknown) {
  return vi.fn().mockResolvedValue(
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

describe("apiFetch", () => {
  beforeEach(() => {
    vi.spyOn(redirect, "go").mockImplementation(() => {});
  });

  it("sends the bearer token and a JSON body", async () => {
    const fetchMock = respond(201, { id: "c1" });
    vi.stubGlobal("fetch", fetchMock);
    const result = await apiFetch<{ id: string }>("/api/v1/classes", {
      method: "POST",
      body: { name: "9A" },
    });
    expect(result).toEqual({ id: "c1" });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ name: "9A" }));
    expect(init.headers).toMatchObject({
      Authorization: "Bearer token-123",
      "Content-Type": "application/json",
    });
  });

  it("returns undefined for 204", async () => {
    vi.stubGlobal("fetch", respond(204));
    await expect(apiFetch("/api/v1/x", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("on 401 signs out and goes to /login", async () => {
    vi.stubGlobal("fetch", respond(401, { code: "unauthenticated", message: "Please sign in" }));
    const error = await apiFetch("/api/v1/me").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("unauthenticated");
    expect(supabase.signOut).toHaveBeenCalled();
    expect(redirect.go).toHaveBeenCalledWith("/login");
  });

  it("on password_change_required goes to /change-password without signing out", async () => {
    supabase.signOut.mockClear();
    vi.stubGlobal("fetch", respond(403, { code: "password_change_required", message: "x" }));
    await expect(apiFetch("/api/v1/classes")).rejects.toMatchObject({
      status: 403,
      code: "password_change_required",
    });
    expect(redirect.go).toHaveBeenCalledWith("/change-password");
    expect(supabase.signOut).not.toHaveBeenCalled();
  });

  it("surfaces conflict and validation messages", async () => {
    vi.stubGlobal("fetch", respond(409, { code: "last_admin", message: "A school needs..." }));
    await expect(apiFetch("/api/v1/teachers/x")).rejects.toMatchObject({
      status: 409,
      code: "last_admin",
      message: "A school needs...",
    });
    vi.stubGlobal(
      "fetch",
      respond(422, { detail: [{ msg: "Value error, At most 60 students at a time." }] }),
    );
    await expect(apiFetch("/api/v1/x")).rejects.toMatchObject({
      message: "At most 60 students at a time.",
    });
    expect(redirect.go).not.toHaveBeenCalled();
  });
});
