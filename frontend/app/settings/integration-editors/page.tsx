"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { AppNav } from "@/components/AppNav";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ApiError,
  addIntegrationEditor,
  fetchIntegrationEditors,
  removeIntegrationEditorFlag,
  type IntegrationEditorRow,
} from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";

export default function IntegrationEditorsPage() {
  const router = useRouter();
  const accessToken = useAuthStore((s) => s.accessToken);
  const hasHydrated = useAuthStore((s) => s._hasHydrated);
  const canManageIntegrationEditors = useAuthStore(
    (s) => s.canManageIntegrationEditors,
  );
  const canRevokeIntegrationEditorAccess = useAuthStore(
    (s) => s.canRevokeIntegrationEditorAccess,
  );
  const isSuperAdmin = useAuthStore((s) => s.isSuperAdmin);
  const sessionEmail = useAuthStore((s) => s.email);

  const [rows, setRows] = useState<IntegrationEditorRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    if (!hasHydrated) return;
    if (!accessToken) {
      router.replace("/login");
      return;
    }
    if (canManageIntegrationEditors === null) return;
    if (canManageIntegrationEditors !== true) {
      router.replace("/settings");
      return;
    }
    let cancelled = false;
    setLoading(true);
    setErr(null);
    void fetchIntegrationEditors()
      .then((r) => {
        if (!cancelled) setRows(r);
      })
      .catch((e) => {
        if (!cancelled) {
          setErr(
            e instanceof ApiError ? e.message : "Не удалось загрузить список",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [hasHydrated, accessToken, canManageIntegrationEditors, router]);

  async function onAdd(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setAdding(true);
    try {
      const row = await addIntegrationEditor(email.trim());
      setRows((prev) => {
        const others = prev.filter((x) => x.id !== row.id);
        const next = [...others, row];
        next.sort((a, b) => a.email.localeCompare(b.email));
        return next;
      });
      setEmail("");
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Не удалось добавить");
    } finally {
      setAdding(false);
    }
  }

  async function onRevoke(id: string) {
    setErr(null);
    try {
      await removeIntegrationEditorFlag(id);
      setRows((prev) =>
        prev
          .map((r) =>
            r.id === id
              ? { ...r, can_edit_integration_settings: false, is_admin: false }
              : r,
          )
          .filter((r) => r.is_admin || r.can_edit_integration_settings),
      );
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Не удалось отозвать право");
    }
  }

  if (!hasHydrated) {
    return (
      <main className="flex min-h-screen items-center justify-center p-4">
        <p className="text-muted-foreground">Загрузка…</p>
      </main>
    );
  }
  if (!accessToken) {
    return (
      <main className="flex min-h-screen items-center justify-center p-4">
        <p className="text-muted-foreground">Перенаправление…</p>
      </main>
    );
  }
  if (canManageIntegrationEditors === null) {
    return (
      <>
        <AppNav />
        <main className="mx-auto w-full max-w-3xl px-4 py-6 lg:px-6 lg:py-10">
          <p className="text-muted-foreground">Загрузка профиля…</p>
        </main>
      </>
    );
  }
  if (canManageIntegrationEditors !== true) {
    return null;
  }

  return (
    <>
      <AppNav />
      <main className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6 lg:px-6 lg:py-10">
        <div className="space-y-1">
          <h1 className="text-2xl font-display font-bold tracking-tight">
            Редакторы глобальных настроек
          </h1>
          <p className="text-sm text-muted-foreground">
            Укажите электронную почту зарегистрированного пользователя, чтобы
            разрешить ему менять настройки языковой модели, e-staff и HeadHunter.
            Администраторы системы имеют такой доступ всегда.
          </p>
        </div>

        <Link
          href="/settings"
          className="inline-block text-sm text-primary font-medium hover:underline"
        >
          ← Назад к настройкам
        </Link>

        <Card>
          <CardHeader>
            <CardTitle>Добавить по почте</CardTitle>
            <CardDescription>
              Пользователь должен уже существовать в системе (регистрация или вход
              через провайдера).
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={(e) => void onAdd(e)} className="flex flex-col gap-4 sm:flex-row sm:items-end">
              <div className="min-w-0 flex-1 space-y-2">
                <Label htmlFor="editor-email">Электронная почта</Label>
                <Input
                  id="editor-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="colleague@company.ru"
                  required
                  autoComplete="off"
                />
              </div>
              <Button type="submit" disabled={adding || !email.trim()}>
                {adding ? "Добавление…" : "Выдать право"}
              </Button>
            </form>
          </CardContent>
        </Card>

        {err ? (
          <div className="rounded-lg border-2 border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
            {err}
          </div>
        ) : null}

        <Card>
          <CardHeader>
            <CardTitle>Текущий доступ</CardTitle>
            <CardDescription>
              Отозвать доступ к глобальным настройкам (в том числе у
              администратора в базе данных) может только супер-администратор из
              базы данных. Остальные видят список и могут выдавать права, но не
              снимать их.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <p className="text-sm text-muted-foreground">Загрузка…</p>
            ) : rows.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Пока нет записей с явным правом или администраторов в списке.
              </p>
            ) : (
              <ul className="divide-y divide-border rounded-md border border-border">
                {rows.map((r) => {
                  const sameAsSession =
                    sessionEmail != null &&
                    sessionEmail.trim().toLowerCase() ===
                      r.email.trim().toLowerCase();
                  const showRevoke =
                    (isSuperAdmin === true ||
                      canRevokeIntegrationEditorAccess === true) &&
                    (r.is_admin || r.can_edit_integration_settings) &&
                    !sameAsSession;
                  return (
                    <li
                      key={r.id}
                      className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
                    >
                      <div className="min-w-0">
                        <p className="truncate font-medium">{r.email}</p>
                        <p className="text-xs text-muted-foreground">
                          {[
                            r.is_admin ? "Администратор системы" : null,
                            r.can_edit_integration_settings
                              ? "Назначен редактором настроек"
                              : null,
                          ]
                            .filter(Boolean)
                            .join(" · ") || "—"}
                        </p>
                      </div>
                      {showRevoke ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="shrink-0"
                          onClick={() => void onRevoke(r.id)}
                        >
                          Отозвать доступ к настройкам
                        </Button>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
          </CardContent>
        </Card>
      </main>
    </>
  );
}
