import { Markdown } from "@/components/markdown/Markdown";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";

import { useNotice } from "./api";

/** Spec 014: the AI-tutor notice and what the app stores, for any signed-in user. */
export function PrivacyPage() {
  const notice = useNotice();
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Privacy" />
      {notice.isPending ? (
        <Skeleton className="h-96" aria-busy />
      ) : notice.isError ? (
        <p role="alert" className="text-sm text-destructive">
          Couldn't load the privacy notice.
        </p>
      ) : (
        <div className="space-y-8">
          <Markdown>{notice.data.body_md}</Markdown>
          <Markdown>{notice.data.stores_md}</Markdown>
          <p className="text-xs text-muted-foreground">Notice version {notice.data.version}</p>
        </div>
      )}
    </div>
  );
}
