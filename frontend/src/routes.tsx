import type { RouteObject } from "react-router";

import { AppShell } from "@/components/layout/AppShell";
import { ChangePasswordPage } from "@/features/auth/ChangePasswordPage";
import { RequireAuth, RequireRole } from "@/features/auth/guards";
import { LoginPage } from "@/features/auth/LoginPage";
import { SetPasswordPage } from "@/features/auth/SetPasswordPage";
import { HomePage } from "@/pages/HomePage";
import { NotFoundPage } from "@/pages/NotFoundPage";

export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  { path: "/accept-invite", element: <SetPasswordPage mode="invite" /> },
  { path: "/reset-password", element: <SetPasswordPage mode="reset" /> },
  {
    element: <RequireAuth />,
    children: [
      { path: "/change-password", element: <ChangePasswordPage /> },
      {
        element: <AppShell />,
        children: [
          { path: "/", element: <HomePage /> },
          { element: <RequireRole access="staff" />, children: [] },
          { element: <RequireRole access="admin" />, children: [] },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
];
