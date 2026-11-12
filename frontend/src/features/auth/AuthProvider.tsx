import type { Session } from "@supabase/supabase-js";
import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { slipsStore } from "@/features/slips/store";
import { setObservedUser } from "@/lib/observability";
import { getSupabase, signOut as supabaseSignOut } from "@/lib/supabase";

type AuthContextValue = {
  session: Session | null;
  /** True until the stored session (or one from an invite/reset link) has been read. */
  loading: boolean;
  signInWithPassword: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const auth = getSupabase().auth;
    let active = true;
    void auth.getSession().then(({ data }) => {
      if (!active) return;
      setSession(data.session);
      setLoading(false);
    });
    const { data } = auth.onAuthStateChange((event, next) => {
      if (event === "SIGNED_OUT" || !next) {
        // Also a sign-out in another tab, a failed refresh or a revoked session: on a shared lab
        // computer nothing of the last user may stay in memory (spec 015 review, area 12).
        queryClient.clear();
        slipsStore.clear();
        setObservedUser(null);
      }
      setSession(next);
      setLoading(false);
    });
    return () => {
      active = false;
      data.subscription.unsubscribe();
    };
  }, [queryClient]);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      loading,
      async signInWithPassword(email, password) {
        const { error } = await getSupabase().auth.signInWithPassword({ email, password });
        if (error) throw error;
        queryClient.clear();
        slipsStore.clear(); // never the previous teacher's temp passwords
      },
      async signOut() {
        await supabaseSignOut();
        queryClient.clear();
        setObservedUser(null);
        slipsStore.clear(); // temp passwords must not outlive the session on a shared computer
      },
    }),
    [session, loading, queryClient],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
