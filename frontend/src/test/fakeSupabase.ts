import type { Session } from "@supabase/supabase-js";
import { vi } from "vitest";

type Listener = (event: string, session: Session | null) => void;

/** A controllable stand-in for the Supabase client. Use with `vi.mock("@/lib/supabase", ...)`. */
export function createFakeSupabase() {
  const state = { session: null as Session | null, listeners: [] as Listener[] };

  const setSession = (session: Session | null) => {
    state.session = session;
    state.listeners.forEach((l) => l(session ? "SIGNED_IN" : "SIGNED_OUT", session));
  };

  const auth = {
    getSession: vi.fn(async () => ({ data: { session: state.session }, error: null })),
    onAuthStateChange: vi.fn((listener: Listener) => {
      state.listeners.push(listener);
      return { data: { subscription: { unsubscribe: vi.fn() } } };
    }),
    signInWithPassword: vi.fn(async ({ email }: { email: string; password: string }) => {
      const session = fakeSession(email);
      setSession(session);
      return { data: { session }, error: null as unknown };
    }),
    signOut: vi.fn(async () => {
      setSession(null);
      return { error: null };
    }),
    resetPasswordForEmail: vi.fn(async () => ({ data: {}, error: null })),
    updateUser: vi.fn(async () => ({ data: {}, error: null })),
  };

  return { state, auth, setSession, client: { auth } };
}

export function fakeSession(email = "t@x.in"): Session {
  return {
    access_token: "token-123",
    refresh_token: "r",
    expires_in: 3600,
    token_type: "bearer",
    user: { id: "u1", email, app_metadata: {}, user_metadata: {}, aud: "authenticated" },
  } as unknown as Session;
}
