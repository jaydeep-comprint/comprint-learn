import { createClient, type SupabaseClient } from "@supabase/supabase-js";

let client: SupabaseClient | null = null;

/** The browser Supabase client (anon key). Created on first use so tests can mock this module. */
export function getSupabase(): SupabaseClient {
  if (!client) {
    const url = import.meta.env.VITE_SUPABASE_URL;
    const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;
    if (!url || !anonKey) {
      throw new Error("VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY are not set (frontend/.env).");
    }
    client = createClient(url, anonKey, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
    });
  }
  return client;
}

/** The current access token, refreshed by supabase-js if it is about to expire. */
export async function getAccessToken(): Promise<string | null> {
  const { data } = await getSupabase().auth.getSession();
  return data.session?.access_token ?? null;
}

export async function signOut(): Promise<void> {
  // "local": clear this device's session even if the server is unreachable.
  await getSupabase().auth.signOut({ scope: "local" });
}
