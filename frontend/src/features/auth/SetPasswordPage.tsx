import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { FullPageSpinner } from "@/components/FullPageSpinner";
import { Button } from "@/components/ui/button";
import { AuthLayout } from "@/features/auth/AuthLayout";
import { AUTH_UNREACHABLE, LINK_EXPIRED } from "@/features/auth/authErrors";
import { useAuth } from "@/features/auth/AuthProvider";
import { NewPasswordForm } from "@/features/auth/NewPasswordForm";
import { ME_KEY } from "@/features/auth/useMe";
import { getSupabase } from "@/lib/supabase";

/** Supabase puts `error_code=otp_expired` etc. in the URL hash when a link is invalid. */
function linkHasError(): boolean {
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const query = new URLSearchParams(window.location.search);
  return hash.has("error") || hash.has("error_code") || query.has("error");
}

/** `/accept-invite` and `/reset-password`: the link signs the user in; they choose a password. */
export function SetPasswordPage({ mode }: { mode: "invite" | "reset" }) {
  const { session, loading } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [badLink] = useState(linkHasError);

  if (loading) return <FullPageSpinner />;

  const title = mode === "invite" ? "Welcome! Choose a password" : "Choose a new password";
  if (badLink || !session) {
    return (
      <AuthLayout title={title}>
        <div className="grid gap-4">
          <p role="alert" className="text-sm text-destructive">
            {mode === "invite" ? LINK_EXPIRED : "This link has expired. Request a new one."}
          </p>
          <Button asChild variant="outline">
            <Link to="/login">Back to sign in</Link>
          </Button>
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title={title} description={session.user.email}>
      <NewPasswordForm
        submitLabel="Save password"
        onSubmit={async (password) => {
          const { error } = await getSupabase().auth.updateUser({ password });
          if (error) {
            return (error.status ?? 0) >= 500 || error.name === "AuthRetryableFetchError"
              ? AUTH_UNREACHABLE
              : error.message;
          }
          // The first authenticated /me call activates an invited teacher.
          await queryClient.invalidateQueries({ queryKey: ME_KEY });
          navigate("/", { replace: true });
          return null;
        }}
      />
    </AuthLayout>
  );
}
