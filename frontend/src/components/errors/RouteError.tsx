import { useMemo } from "react";
import { useRouteError } from "react-router";

import { errorCode } from "@/components/errors/codes";
import { ErrorScreen } from "@/components/errors/ErrorScreen";
import { reportError } from "@/lib/observability";

/** The router's `errorElement` (spec 015): a render or loader error inside any route. */
export function RouteError() {
  const error = useRouteError();
  // Reported once per error object (Sentry also dedupes a repeat of the same object).
  const eventId = useMemo(() => reportError(error), [error]);
  return <ErrorScreen code={errorCode(error, eventId)} />;
}
