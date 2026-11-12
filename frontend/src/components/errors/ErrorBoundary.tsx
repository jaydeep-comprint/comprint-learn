import { Component, type ReactNode } from "react";

import { errorCode } from "@/components/errors/codes";
import { ErrorScreen } from "@/components/errors/ErrorScreen";
import { reportError } from "@/lib/observability";

type State = { error: unknown; code: string | null } | null;

/** Root boundary (spec 015): anything that escapes the router's error element. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: State }> {
  state: { failed: State } = { failed: null };

  static getDerivedStateFromError(error: unknown) {
    return { failed: { error, code: null } };
  }

  componentDidCatch(error: unknown) {
    const eventId = reportError(error);
    this.setState({ failed: { error, code: errorCode(error, eventId) } });
  }

  render() {
    if (this.state.failed) return <ErrorScreen code={this.state.failed.code} />;
    return this.props.children;
  }
}
