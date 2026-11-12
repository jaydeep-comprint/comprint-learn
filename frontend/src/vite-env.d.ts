/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_SUPABASE_URL?: string;
  readonly VITE_SUPABASE_ANON_KEY?: string;
  /** Spec 015: Sentry (EU). Unset = error tracking off. */
  readonly VITE_SENTRY_DSN?: string;
}
