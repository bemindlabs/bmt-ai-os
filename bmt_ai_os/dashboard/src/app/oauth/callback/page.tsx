"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { oauthCallback } from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { CheckCircle2, XCircle, Loader2 } from "lucide-react";

type CallbackStatus = "exchanging" | "success" | "error";

function OAuthCallbackView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<CallbackStatus>("exchanging");
  const [message, setMessage] = useState("");
  const [providerName, setProviderName] = useState("");

  useEffect(() => {
    async function exchangeCode() {
      const code = searchParams.get("code");
      const state = searchParams.get("state");
      const error = searchParams.get("error");
      const errorDescription = searchParams.get("error_description");

      // Retrieve stored OAuth context
      const storedProvider =
        sessionStorage.getItem("bmt_oauth_provider") ?? "";
      const storedState = sessionStorage.getItem("bmt_oauth_state") ?? "";
      setProviderName(storedProvider);

      // Clean up session storage
      sessionStorage.removeItem("bmt_oauth_provider");
      sessionStorage.removeItem("bmt_oauth_state");

      if (error) {
        setStatus("error");
        setMessage(errorDescription ?? error);
        return;
      }

      if (!code || !state) {
        setStatus("error");
        setMessage("Missing authorization code or state parameter.");
        return;
      }

      if (state !== storedState) {
        setStatus("error");
        setMessage(
          "OAuth state mismatch \u2014 this may be a CSRF attack or an expired link.",
        );
        return;
      }

      if (!storedProvider) {
        setStatus("error");
        setMessage(
          "No provider context found. Please start the OAuth flow again.",
        );
        return;
      }

      try {
        const redirectUri = `${window.location.origin}/oauth/callback`;
        const result = await oauthCallback(
          storedProvider,
          code,
          state,
          redirectUri,
        );
        setStatus("success");
        setMessage(
          `Connected to ${result.provider_name}. Token expires in ${Math.round(result.expires_in / 60)} minutes.`,
        );
      } catch (err) {
        setStatus("error");
        setMessage(
          err instanceof Error ? err.message : "Token exchange failed.",
        );
      }
    }

    void exchangeCode();
    // Run only once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleContinue() {
    sessionStorage.removeItem("bmt_oauth_wizard");
    router.push("/models");
  }

  return (
    <Card className="w-full max-w-md">
      <CardHeader className="text-center">
        <div className="mx-auto mb-3">
          {status === "exchanging" && (
            <div className="flex size-12 items-center justify-center rounded-full bg-muted">
              <Loader2 className="size-6 animate-spin text-muted-foreground" />
            </div>
          )}
          {status === "success" && (
            <div className="flex size-12 items-center justify-center rounded-full bg-green-500/10">
              <CheckCircle2 className="size-6 text-green-500" />
            </div>
          )}
          {status === "error" && (
            <div className="flex size-12 items-center justify-center rounded-full bg-destructive/10">
              <XCircle className="size-6 text-destructive" />
            </div>
          )}
        </div>
        <CardTitle className="text-lg">
          {status === "exchanging" && "Completing OAuth..."}
          {status === "success" && "OAuth Connected"}
          {status === "error" && "OAuth Failed"}
        </CardTitle>
        <CardDescription>
          {providerName && (
            <span className="capitalize">{providerName} provider</span>
          )}
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4 text-center">
        {message && (
          <p
            className={`text-sm ${status === "error" ? "text-destructive" : "text-muted-foreground"}`}
          >
            {message}
          </p>
        )}

        {status !== "exchanging" && (
          <div className="flex justify-center gap-2">
            <Button onClick={handleContinue}>
              {status === "success"
                ? "Continue to Models"
                : "Back to Models"}
            </Button>
            {status === "error" && (
              <Button
                variant="outline"
                onClick={() => router.push("/models")}
              >
                Try Again
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function OAuthCallbackPage() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center p-4">
      <Suspense
        fallback={
          <Card className="w-full max-w-md">
            <CardContent className="flex items-center justify-center py-12">
              <Loader2 className="size-6 animate-spin text-muted-foreground" />
            </CardContent>
          </Card>
        }
      >
        <OAuthCallbackView />
      </Suspense>
    </div>
  );
}
