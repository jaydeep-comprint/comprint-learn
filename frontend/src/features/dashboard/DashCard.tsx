import { AlertCircle } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export type Query<T> = {
  data: T | undefined;
  isPending: boolean;
  isError: boolean;
  refetch: () => unknown;
};

/** A dashboard card with its own loading skeleton and "Try again" error (spec 010). */
export function DashCard<T>({
  title,
  description,
  action,
  query,
  children,
  className,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  query: Query<T>;
  children: (data: T) => ReactNode;
  className?: string;
}) {
  return (
    <Card className={className}>
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <div className="space-y-1">
          <CardTitle>{title}</CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </div>
        {action}
      </CardHeader>
      <CardContent>
        {query.isPending ? (
          <div className="space-y-2" aria-busy="true">
            <Skeleton className="h-6" />
            <Skeleton className="h-6" />
            <Skeleton className="h-6 w-2/3" />
          </div>
        ) : query.isError || query.data === undefined ? (
          <div role="alert" className="flex items-center gap-3 text-sm">
            <AlertCircle className="size-4 text-destructive" aria-hidden />
            <span>Couldn&apos;t load this.</span>
            <Button variant="outline" size="sm" onClick={() => void query.refetch()}>
              Try again
            </Button>
          </div>
        ) : (
          children(query.data)
        )}
      </CardContent>
    </Card>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}
