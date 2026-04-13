"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ApiError, exchangeOAuthHandoff, fetchAuthMe } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";

const handoffInFlight = new Map<
  string,
  Promise<{ accessToken: string; refreshToken: string }>
>();

function exchangeHandoffOnce(code: string) {
  const c = code.trim();
  let p = handoffInFlight.get(c);
  if (!p) {
    p = exchangeOAuthHandoff(c).finally(() => {
      setTimeout(() => handoffInFlight.delete(c), 60_000);
    });
    handoffInFlight.set(c, p);
  }
  return p;
}

function oauthErrorMessage(
  code: string | null,
  description: string | null,
): string {
  const d = (description || "").trim();
  if (d) {
    const lower = d.toLowerCase();
    if (lower.includes("access_denied") || code === "access_denied") {
      return "Вход отменён. Вы можете попробовать снова.";
    }
    return d.length > 200 ? `${d.slice(0, 197)}…` : d;
  }
  switch (code) {
    case "access_denied":
      return "Вход отменён. Вы можете попробовать снова.";
    case "invalid_state":
      return "Сессия входа устарела или повреждена. Откройте вход снова.";
    case "invalid_request":
      return "Запрос входа неполный. Повторите попытку со страницы входа.";
    case "token_exchange":
      return "Не удалось завершить вход у провайдера. Повторите позже.";
    case "profile":
      return "Провайдер не передал достаточно данных для входа.";
    default:
      return code
        ? "Вход не выполнен. Повторите попытку."
        : "Не удалось завершить вход.";
  }
}

function stripUrlHashOnce() {
  if (typeof window !== "undefined" && window.location.hash) {
    const path = `${window.location.pathname}${window.location.search}`;
    window.history.replaceState(null, "", path);
  }
}

function FinishInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const oauthErr = searchParams.get("oauth_error");
  const oauthDesc = searchParams.get("oauth_error_description");
  const codeFromQuery = searchParams.get("code");
  const queryKey = searchParams.toString();
  const setSession = useAuthStore((s) => s.setSession);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (oauthErr || oauthDesc) {
      setError(oauthErrorMessage(oauthErr, oauthDesc));
      setLoading(false);
      return;
    }

    const hash =
      typeof window !== "undefined" && window.location.hash.startsWith("#")
        ? window.location.hash.slice(1)
        : "";
    const hashParams = new URLSearchParams(hash);
    const codeFromHash = hashParams.get("code");
    const code = (codeFromHash || codeFromQuery || "").trim();
    if (!code) {
      setError("Отсутствует код подтверждения. Откройте вход с главной страницы.");
      setLoading(false);
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const tokens = await exchangeHandoffOnce(code);
        if (cancelled) return;
        setSession({ ...tokens, email: null });
        const me = await fetchAuthMe(tokens.accessToken);
        if (cancelled) return;
        setSession({
          ...tokens,
          email: me.email,
          isAdmin: me.is_admin,
          isSuperAdmin: me.is_super_admin,
          canWriteIntegrationSettings: me.can_write_integration_settings,
          canManageIntegrationEditors: me.can_manage_integration_editors,
          canRevokeIntegrationEditorAccess: me.can_revoke_integration_editor_access,
        });
        stripUrlHashOnce();
        router.replace("/search");
      } catch (err) {
        if (cancelled) return;
        setError(
          err instanceof ApiError
            ? err.message
            : "Не удалось завершить вход. Повторите попытку.",
        );
        stripUrlHashOnce();
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [queryKey, oauthErr, oauthDesc, codeFromQuery, router, setSession]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-gradient-to-br from-background via-secondary/30 to-background p-4">
      <div className="w-full max-w-md space-y-6 animate-fade-in">
        <Card className="shadow-float">
          <CardHeader className="space-y-1">
            <CardTitle className="text-2xl">Завершение входа</CardTitle>
            <CardDescription>
              {loading
                ? "Проверяем данные и открываем сервис…"
                : error
                  ? "Вход не завершён"
                  : "Перенаправление…"}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {loading && !error && (
              <p className="text-sm text-muted-foreground">Подождите несколько секунд.</p>
            )}
            {error && (
              <>
                <div className="rounded-lg border-2 border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                  {error}
                </div>
                <Button asChild className="w-full" variant="secondary">
                  <Link href="/login">Вернуться ко входу</Link>
                </Button>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </main>
  );
}

export default function OAuthFinishPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center p-4">
          <p className="text-muted-foreground">Загрузка…</p>
        </main>
      }
    >
      <FinishInner />
    </Suspense>
  );
}
