import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";
import { toast } from "sonner";

import { FormError } from "@/components/FormError";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AuthLayout } from "@/features/auth/AuthLayout";
import {
  AUTH_UNREACHABLE,
  STAFF_BAD_CREDENTIALS,
  STUDENT_BAD_CREDENTIALS,
  signInErrorMessage,
} from "@/features/auth/authErrors";
import { useAuth } from "@/features/auth/AuthProvider";
import {
  normalizeSchoolCode,
  rememberSchoolCode,
  rememberedSchoolCode,
  studentAuthEmail,
} from "@/features/auth/studentLogin";
import { HealthStatus } from "@/features/health/HealthStatus";
import { getSupabase } from "@/lib/supabase";

function useAfterSignIn() {
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from;
  return () => navigate(from && from !== "/login" ? from : "/", { replace: true });
}

function StudentForm() {
  const { signInWithPassword } = useAuth();
  const done = useAfterSignIn();
  const [code, setCode] = useState(rememberedSchoolCode);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await signInWithPassword(studentAuthEmail(code, username), password);
      rememberSchoolCode(code);
      done();
    } catch (err) {
      setError(signInErrorMessage(err, STUDENT_BAD_CREDENTIALS));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="grid gap-4">
      <div className="grid gap-2">
        <Label htmlFor="school-code">School code</Label>
        <Input
          id="school-code"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          onBlur={() => setCode((c) => normalizeSchoolCode(c))}
          autoCapitalize="characters"
          autoComplete="organization"
          required
        />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="username">Username</Label>
        <Input
          id="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoCapitalize="none"
          autoComplete="username"
          spellCheck={false}
          required
        />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="student-password">Password</Label>
        <Input
          id="student-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          required
        />
      </div>
      <FormError message={error} />
      <Button type="submit" disabled={busy}>
        {busy ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}

function ForgotPasswordDialog({
  open,
  onOpenChange,
  initialEmail,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialEmail: string;
}) {
  const [email, setEmail] = useState(initialEmail);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { error: err } = await getSupabase().auth.resetPasswordForEmail(email.trim(), {
        redirectTo: `${window.location.origin}/reset-password`,
      });
      if (err && (err.status ?? 0) >= 500) throw err;
      // Same message whether or not the email has an account.
      toast.success("If that email has an account, a reset link is on its way.");
      onOpenChange(false);
    } catch {
      setError(AUTH_UNREACHABLE);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reset your password</DialogTitle>
          <DialogDescription>We'll email you a link to choose a new password.</DialogDescription>
        </DialogHeader>
        <form onSubmit={(e) => void submit(e)} className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="reset-email">Email</Label>
            <Input
              id="reset-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <FormError message={error} />
          <DialogFooter>
            <Button type="submit" disabled={busy}>
              {busy ? "Sending…" : "Send reset link"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function StaffForm() {
  const { signInWithPassword } = useAuth();
  const done = useAfterSignIn();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [forgotOpen, setForgotOpen] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await signInWithPassword(email.trim(), password);
      done();
    } catch (err) {
      setError(signInErrorMessage(err, STAFF_BAD_CREDENTIALS));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="grid gap-4">
      <div className="grid gap-2">
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
          required
        />
      </div>
      <div className="grid gap-2">
        <div className="flex items-center justify-between">
          <Label htmlFor="staff-password">Password</Label>
          <Button
            type="button"
            variant="link"
            className="h-auto p-0 text-sm"
            onClick={() => setForgotOpen(true)}
          >
            Forgot password?
          </Button>
        </div>
        <Input
          id="staff-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          required
        />
      </div>
      <FormError message={error} />
      <Button type="submit" disabled={busy}>
        {busy ? "Signing in…" : "Sign in"}
      </Button>
      {forgotOpen && (
        <ForgotPasswordDialog open={forgotOpen} onOpenChange={setForgotOpen} initialEmail={email} />
      )}
    </form>
  );
}

export function LoginPage() {
  const { session, loading } = useAuth();
  if (!loading && session) return <Navigate to="/" replace />;

  return (
    <AuthLayout
      title="Sign in"
      description="Students use the details on their login slip."
      footer={
        <footer className="text-xs">
          <HealthStatus />
        </footer>
      }
    >
      <Tabs defaultValue="student">
        <TabsList className="mb-2 w-full">
          <TabsTrigger value="student">Student</TabsTrigger>
          <TabsTrigger value="staff">Staff</TabsTrigger>
        </TabsList>
        <TabsContent value="student">
          <StudentForm />
        </TabsContent>
        <TabsContent value="staff">
          <StaffForm />
        </TabsContent>
      </Tabs>
    </AuthLayout>
  );
}
