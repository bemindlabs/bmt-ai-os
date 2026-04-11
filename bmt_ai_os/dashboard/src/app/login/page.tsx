"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { login } from "@/lib/auth";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Cpu, Lock, Eye, EyeOff } from "lucide-react";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      await login(username, password);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="relative flex min-h-screen w-screen items-center justify-center overflow-hidden bg-background px-4">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(255,255,255,.02)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.02)_1px,transparent_1px)] bg-[size:64px_64px]" />
      <div className="pointer-events-none absolute -top-40 left-1/2 h-80 w-[600px] -translate-x-1/2 rounded-full bg-primary/5 blur-3xl" />

      <div className="relative z-10 w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3">
          <div className="flex size-12 items-center justify-center rounded-xl bg-primary/10 ring-1 ring-primary/20">
            <Cpu className="size-6 text-primary" />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xl font-bold tracking-tight">BMT AI OS</span>
            <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
              v0.1
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground">
            On-device AI operating system
          </p>
        </div>

        <Card className="border-border/50 shadow-2xl shadow-black/20">
          <CardHeader className="space-y-1 pb-4">
            <CardTitle className="text-lg">Welcome back</CardTitle>
            <CardDescription>
              Sign in to access your AI dashboard
            </CardDescription>
          </CardHeader>

          <form onSubmit={handleSubmit}>
            <CardContent className="flex flex-col gap-4">
              {error && (
                <div
                  role="alert"
                  aria-live="polite"
                  className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-xs text-destructive"
                >
                  <Lock className="size-3.5 shrink-0" />
                  {error}
                </div>
              )}

              <div className="flex flex-col gap-1.5">
                <label
                  htmlFor="username"
                  className="text-xs font-medium text-foreground"
                >
                  Username
                </label>
                <Input
                  id="username"
                  type="text"
                  autoComplete="username"
                  autoFocus
                  required
                  placeholder="admin"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  aria-invalid={!!error}
                  className="h-10"
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <label
                  htmlFor="password"
                  className="text-xs font-medium text-foreground"
                >
                  Password
                </label>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    required
                    placeholder="Enter your password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    aria-invalid={!!error}
                    className="h-10 pr-10"
                  />
                  <button
                    type="button"
                    tabIndex={-1}
                    aria-label={
                      showPassword ? "Hide password" : "Show password"
                    }
                    className="absolute right-0 top-0 flex h-10 w-10 items-center justify-center text-muted-foreground transition-colors hover:text-foreground"
                    onClick={() => setShowPassword(!showPassword)}
                  >
                    {showPassword ? (
                      <EyeOff className="size-4" />
                    ) : (
                      <Eye className="size-4" />
                    )}
                  </button>
                </div>
              </div>
            </CardContent>

            <CardFooter className="flex flex-col gap-3 pt-2">
              <Button
                type="submit"
                className="h-10 w-full font-medium"
                disabled={loading || !username || !password}
              >
                {loading ? (
                  <span className="flex items-center gap-2">
                    <span className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                    Signing in...
                  </span>
                ) : (
                  "Sign in"
                )}
              </Button>
              <p className="text-center text-[11px] text-muted-foreground/60">
                Secured with JWT authentication
              </p>
            </CardFooter>
          </form>
        </Card>

        <p className="mt-6 text-center text-[11px] text-muted-foreground/40">
          Bemind Technology Co., Ltd.
        </p>
      </div>
    </div>
  );
}
