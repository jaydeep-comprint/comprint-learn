import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";

import { Button } from "@/components/ui/button";
import { AuthLayout } from "@/features/auth/AuthLayout";
import { useAuth } from "@/features/auth/AuthProvider";
import { NewPasswordForm } from "@/features/auth/NewPasswordForm";
import { ME_KEY, useMe } from "@/features/auth/useMe";
import { ApiError, apiFetch } from "@/lib/api";

/** Forced for students holding a temp password. The only way out is Sign out. */
export function ChangePasswordPage() {
  const { session, signInWithPassword, signOut } = useAuth();
  const { data: me } = useMe();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  return (
    <AuthLayout
      title={
        me ? `Hi ${me.display_name.split(/\s+/)[0]}! Choose your password` : "Choose a password"
      }
      description="Your teacher gave you a temporary password. Pick your own to continue."
      footer={
        <Button
          variant="ghost"
          onClick={() => void signOut().then(() => navigate("/login", { replace: true }))}
        >
          Sign out
        </Button>
      }
    >
      <NewPasswordForm
        submitLabel="Save and continue"
        onSubmit={async (password) => {
          try {
            await apiFetch("/api/v1/me/password", {
              method: "POST",
              body: { new_password: password },
            });
          } catch (err) {
            return err instanceof ApiError && err.message
              ? err.message
              : "Couldn't save your password. Try again.";
          }
          // Changing the password signs out every session, so sign in again with the new one.
          const email = session?.user.email;
          if (email) {
            try {
              await signInWithPassword(email, password);
            } catch {
              navigate("/login", { replace: true });
              return null;
            }
          }
          await queryClient.invalidateQueries({ queryKey: ME_KEY });
          navigate("/", { replace: true });
          return null;
        }}
      />
    </AuthLayout>
  );
}
