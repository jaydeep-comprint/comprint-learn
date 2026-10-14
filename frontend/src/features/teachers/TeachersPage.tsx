import {
  MailPlus,
  MoreHorizontal,
  Send,
  ShieldCheck,
  ShieldOff,
  UserCheck,
  Users,
  UserX,
} from "lucide-react";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";

import { ConfirmDialog, type ConfirmRequest } from "@/components/ConfirmDialog";
import { EmptyState } from "@/components/EmptyState";
import { FormError } from "@/components/FormError";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAuth } from "@/features/auth/AuthProvider";
import { useMe } from "@/features/auth/useMe";
import {
  useInviteTeacher,
  useResendInvite,
  useTeachers,
  useUpdateTeacher,
} from "@/features/teachers/api";
import { errorMessage } from "@/lib/errors";
import type { Teacher } from "@/lib/types";

function InviteDialog() {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const invite = useInviteTeacher();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await invite.mutateAsync({ email: email.trim(), display_name: name.trim() });
      toast.success(`Invite sent to ${email.trim()}`);
      setOpen(false);
      setEmail("");
      setName("");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <MailPlus aria-hidden />
          Invite teacher
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Invite a teacher</DialogTitle>
          <DialogDescription>They'll get an email with a link to set a password.</DialogDescription>
        </DialogHeader>
        <form onSubmit={(e) => void submit(e)} className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="invite-name">Name</Label>
            <Input
              id="invite-name"
              value={name}
              maxLength={80}
              placeholder="Ms Rao"
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="invite-email">Email</Label>
            <Input
              id="invite-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <FormError message={error} />
          <DialogFooter>
            <Button type="submit" disabled={invite.isPending}>
              {invite.isPending ? "Sending…" : "Send invite"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function TeachersPage() {
  const { data: me } = useMe();
  const { signOut } = useAuth();
  const navigate = useNavigate();
  const teachers = useTeachers();
  const update = useUpdateTeacher();
  const resend = useResendInvite();
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null);

  const patch = (t: Teacher, body: { is_admin?: boolean; status?: "active" | "deactivated" }) =>
    update.mutate(
      { id: t.id, ...body },
      {
        onSuccess: () => {
          if (t.id === me?.id && body.status === "deactivated") {
            void signOut().then(() => navigate("/login", { replace: true }));
          }
        },
        onError: (err) => toast.error(errorMessage(err)),
      },
    );

  const deactivate = (t: Teacher) =>
    setConfirmRequest({
      title: t.id === me?.id ? "Deactivate your own account?" : `Deactivate ${t.display_name}?`,
      description:
        t.status === "invited"
          ? "Their invite link will stop working."
          : "They'll be signed out and can't sign in until reactivated.",
      confirmLabel: "Deactivate",
      destructive: true,
      onConfirm: () => patch(t, { status: "deactivated" }),
    });

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Teachers" actions={<InviteDialog />} />
      {teachers.isPending ? (
        <div className="space-y-2" aria-busy>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-10" />
          ))}
        </div>
      ) : teachers.isError ? (
        <p className="text-sm text-destructive">Couldn't load teachers.</p>
      ) : teachers.data.length === 0 ? (
        <EmptyState icon={Users} title="No teachers yet" action={<InviteDialog />} />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="w-10">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {teachers.data.map((t) => (
              <TableRow key={t.id}>
                <TableCell className="font-medium">
                  <span className="flex items-center gap-2">
                    <span className="max-w-48 truncate">{t.display_name}</span>
                    {t.is_admin && <Badge>Admin</Badge>}
                    {t.id === me?.id && (
                      <span className="text-xs text-muted-foreground">(you)</span>
                    )}
                  </span>
                </TableCell>
                <TableCell className="max-w-56 truncate">{t.email}</TableCell>
                <TableCell>
                  <StatusBadge status={t.status} />
                </TableCell>
                <TableCell>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Actions for ${t.display_name}`}
                      >
                        <MoreHorizontal />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      {t.status === "invited" && (
                        <DropdownMenuItem
                          onSelect={() =>
                            resend.mutate(t.id, {
                              onSuccess: () => toast.success("Invite sent again"),
                              onError: (err) => toast.error(errorMessage(err)),
                            })
                          }
                        >
                          <Send aria-hidden />
                          Resend invite
                        </DropdownMenuItem>
                      )}
                      {t.is_admin ? (
                        <DropdownMenuItem onSelect={() => patch(t, { is_admin: false })}>
                          <ShieldOff aria-hidden />
                          Remove admin
                        </DropdownMenuItem>
                      ) : (
                        <DropdownMenuItem onSelect={() => patch(t, { is_admin: true })}>
                          <ShieldCheck aria-hidden />
                          Make admin
                        </DropdownMenuItem>
                      )}
                      {t.status === "deactivated" ? (
                        <DropdownMenuItem onSelect={() => patch(t, { status: "active" })}>
                          <UserCheck aria-hidden />
                          Reactivate
                        </DropdownMenuItem>
                      ) : (
                        <DropdownMenuItem variant="destructive" onSelect={() => deactivate(t)}>
                          <UserX aria-hidden />
                          {t.status === "invited" ? "Revoke invite" : "Deactivate"}
                        </DropdownMenuItem>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <ConfirmDialog request={confirmRequest} onClose={() => setConfirmRequest(null)} />
    </div>
  );
}
