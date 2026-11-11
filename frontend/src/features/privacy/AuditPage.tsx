import { ScrollText } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { istDateTime } from "@/lib/dates";
import type { AuditAction } from "@/lib/types";

import { useAudit } from "./api";
import { AUDIT_LABELS, auditDetails } from "./labels";

/** Spec 014: who recorded consent, downloaded data, erased or changed an account, and when. */
export function AuditPage() {
  const [action, setAction] = useState<AuditAction | null>(null);
  const audit = useAudit(action);
  const items = audit.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Audit log" description="Privacy and account actions in your school." />
      <label className="mb-4 flex max-w-xs flex-col gap-1 text-sm">
        <span className="font-medium">Action</span>
        <select
          className="h-9 rounded-md border bg-background px-2"
          value={action ?? ""}
          onChange={(e) => setAction((e.target.value || null) as AuditAction | null)}
        >
          <option value="">All actions</option>
          {(Object.keys(AUDIT_LABELS) as AuditAction[]).map((a) => (
            <option key={a} value={a}>
              {AUDIT_LABELS[a]}
            </option>
          ))}
        </select>
      </label>

      {audit.isPending ? (
        <div className="space-y-2" aria-busy>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-10" />
          ))}
        </div>
      ) : audit.isError ? (
        <p role="alert" className="text-sm text-destructive">
          Couldn't load the audit log.
        </p>
      ) : items.length === 0 ? (
        <EmptyState icon={ScrollText} title="Nothing recorded yet." />
      ) : (
        <div className="space-y-3">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Who</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Student/Teacher</TableHead>
                  <TableHead>Details</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((e) => (
                  <TableRow key={e.id}>
                    <TableCell className="whitespace-nowrap tabular-nums">
                      {istDateTime(e.at)}
                    </TableCell>
                    <TableCell>{e.actor?.display_name ?? "System"}</TableCell>
                    <TableCell className="whitespace-nowrap">{AUDIT_LABELS[e.action]}</TableCell>
                    <TableCell>{e.target?.display_name ?? "—"}</TableCell>
                    <TableCell className="text-muted-foreground">{auditDetails(e)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {audit.hasNextPage && (
            <Button
              variant="outline"
              disabled={audit.isFetchingNextPage}
              onClick={() => void audit.fetchNextPage()}
            >
              Load more
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
