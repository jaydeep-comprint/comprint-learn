import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";

import { ErrorBoundary } from "@/components/errors/ErrorBoundary";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { initObservability } from "@/lib/observability";
import { createQueryClient } from "@/lib/queryClient";

import "./index.css";
import { routes } from "./routes";

initObservability();

const queryClient = createQueryClient();
const router = createBrowserRouter(routes);

const root = document.getElementById("root");
if (!root) {
  throw new Error("#root element not found");
}

createRoot(root).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <RouterProvider router={router} />
          <Toaster position="top-center" richColors />
        </AuthProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
);
