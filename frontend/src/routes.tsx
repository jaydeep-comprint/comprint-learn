import type { RouteObject } from "react-router";

import { AppShell } from "@/components/layout/AppShell";
import { ChangePasswordPage } from "@/features/auth/ChangePasswordPage";
import { RequireAuth, RequireRole } from "@/features/auth/guards";
import { LoginPage } from "@/features/auth/LoginPage";
import { SetPasswordPage } from "@/features/auth/SetPasswordPage";
import { ClassesPage } from "@/features/classes/ClassesPage";
import { ClassLayout } from "@/features/dashboard/ClassLayout";
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
          {
            // Spec 012: the placement check, also full-screen.
            path: "/placement/:id",
            lazy: async () => ({
              Component: (await import("@/features/placement/PlacementPage")).PlacementPage,
            }),
          },
          {
            path: "/placement/:id/result",
            lazy: async () => ({
              Component: (await import("@/features/placement/PlacementResult")).PlacementResult,
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
              {
                // Spec 010: the class dashboard; tabs are nested routes (lazy).
                path: "/classes/:id",
                element: <ClassLayout />,
                children: [
                  {
                    index: true,
                    lazy: async () => ({
                      Component: (await import("@/features/dashboard/OverviewTab")).OverviewTab,
                    }),
                  },
                  {
                    path: "students",
                    lazy: async () => ({
                      Component: (await import("@/features/dashboard/StudentsTab")).StudentsTab,
                    }),
                  },
                  {
                    path: "students/:studentId",
                    lazy: async () => ({
                      Component: (await import("@/features/dashboard/StudentPage")).StudentPage,
                    }),
                  },
                  {
                    path: "assignments",
                    lazy: async () => ({
                      Component: (await import("@/features/assignments/AssignmentsTab"))
                        .AssignmentsTab,
                    }),
                  },
                  {
                    path: "placement",
                    lazy: async () => ({
                      Component: (await import("@/features/placement/PlacementTab"))
                        .PlacementTab,
                    }),
                  },
                  {
                    path: "settings",
                    lazy: async () => ({
                      Component: (await import("@/features/dashboard/SettingsTab")).SettingsTab,
                    }),
                  },
                ],
              },
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
