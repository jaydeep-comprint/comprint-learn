import { Navigate, Outlet, useLocation } from "react-router";

import { FullPageSpinner } from "@/components/FullPageSpinner";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/features/auth/AuthProvider";
import { useMe } from "@/features/auth/useMe";
import { hasAccess, type Access } from "@/lib/access";
import { ForbiddenPage } from "@/pages/ForbiddenPage";

/** Signed in, known to our API, and (unless on /change-password) not holding a temp password. */
export function RequireAuth() {
  const { session, loading } = useAuth();
  const location = useLocation();
  const me = useMe();

  if (loading) return <FullPageSpinner />;
  if (!session) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (me.isPending) return <FullPageSpinner />;
  if (me.isError) {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-3 p-4 text-center">
        <p className="text-muted-foreground">We couldn't load your account.</p>
        <Button variant="outline" onClick={() => void me.refetch()}>
          Try again
        </Button>
      </div>
    );
  }
  const onChangePassword = location.pathname === "/change-password";
  if (me.data.must_change_password && !onChangePassword) {
    return <Navigate to="/change-password" replace />;
  }
  if (!me.data.must_change_password && onChangePassword) {
    return <Navigate to="/" replace />;
  }
  return <Outlet />;
}

/** Must be rendered inside `RequireAuth`. Wrong role → a 403 page with a link home. */
export function RequireRole({ access }: { access: Access }) {
  const { data: me } = useMe();
  if (!me) return <FullPageSpinner />;
  return hasAccess(me, access) ? <Outlet /> : <ForbiddenPage />;
}
