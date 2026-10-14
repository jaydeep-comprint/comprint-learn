import type { RouteObject } from "react-router";

import { AppShell } from "@/components/layout/AppShell";
import { ChangePasswordPage } from "@/features/auth/ChangePasswordPage";
import { RequireAuth, RequireRole } from "@/features/auth/guards";
import { LoginPage } from "@/features/auth/LoginPage";
import { SetPasswordPage } from "@/features/auth/SetPasswordPage";
import { ClassDetailPage } from "@/features/classes/ClassDetailPage";
import { ClassesPage } from "@/features/classes/ClassesPage";
import { SlipsView } from "@/features/slips/SlipsView";
import { StudentsPage } from "@/features/students/StudentsPage";
import { TeachersPage } from "@/features/teachers/TeachersPage";
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
          {
            element: <RequireRole access="staff" />,
            children: [
              { path: "/classes", element: <ClassesPage /> },
              { path: "/classes/:id", element: <ClassDetailPage /> },
              { path: "/classes/:id/slips", element: <SlipsView /> },
              { path: "/slips", element: <SlipsView /> },
              { path: "/students", element: <StudentsPage /> },
            ],
          },
          {
            element: <RequireRole access="admin" />,
            children: [{ path: "/teachers", element: <TeachersPage /> }],
          },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
];
