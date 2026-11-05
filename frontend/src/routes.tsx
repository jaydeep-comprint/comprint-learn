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
        // Spec 007: the quiz renders without the app navigation (no notes).
        element: <RequireRole access="student" />,
        children: [
          {
            path: "/quiz/:id",
            lazy: async () => ({
              Component: (await import("@/features/quiz/QuizPage")).QuizPage,
            }),
          },
        ],
      },
      {
        element: <AppShell />,
        children: [
          { path: "/", element: <HomePage /> },
          // Any signed-in role: students learn, staff preview (nothing is saved).
          // Lazy: these pull in react-markdown + KaTeX, which staff admin pages don't need.
          {
            path: "/learn/:course",
            lazy: async () => ({
              Component: (await import("@/features/learn/CoursePage")).CoursePage,
            }),
          },
          {
            path: "/learn/brush-up/:id",
            lazy: async () => ({
              Component: (await import("@/features/learn/RemediationPage")).RemediationPage,
            }),
          },
          {
            path: "/learn/:course/:conceptCourse/:conceptSlug",
            lazy: async () => ({
              Component: (await import("@/features/learn/LessonPage")).LessonPage,
            }),
          },
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
            element: <RequireRole access="student" />,
            children: [
              {
                path: "/review/:course/:concept",
                lazy: async () => ({
                  Component: (await import("@/features/reviews/ReviewPage")).ReviewPage,
                }),
              },
              {
                path: "/leaderboard/:classId",
                lazy: async () => ({
                  Component: (await import("@/features/xp/LeaderboardPage")).LeaderboardPage,
                }),
              },
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
