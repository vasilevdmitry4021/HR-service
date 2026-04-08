"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AppNav } from "@/components/AppNav";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, fetchEstaffExportsHistory, sanitizeApiErrorMessage } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";

const PAGE_SIZE = 20;

function formatWhen(iso: string | null | undefined) {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat("ru-RU", {
      dateStyle: "short",
      timeStyle: "short",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function stageLabel(stage: string | null | undefined): string | null {
  if (!stage?.trim()) return null;
  const s = stage.trim();
  if (s === "fetch_resume") return "получение резюме";
  if (s === "preparation") return "подготовка данных";
  if (s === "estaff_api") return "создание в e-staff";
  return s;
}

/** Публичная страница резюме на HeadHunter (как в серверном hh_client). */
function hhResumePublicUrl(resumeId: string | null | undefined): string | null {
  const id = resumeId?.trim();
  if (!id) return null;
  return `https://hh.ru/resume/${encodeURIComponent(id)}`;
}

export default function EstaffExportsPage() {
  const router = useRouter();
  const accessToken = useAuthStore((s) => s.accessToken);
  const hasHydrated = useAuthStore((s) => s._hasHydrated);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [items, setItems] = useState<
    Awaited<ReturnType<typeof fetchEstaffExportsHistory>>["items"]
  >([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!hasHydrated) return;
    if (!accessToken) router.replace("/login");
  }, [hasHydrated, accessToken, router]);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      const data = await fetchEstaffExportsHistory(page, PAGE_SIZE);
      setItems(data.items);
      setTotal(data.total);
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Не удалось загрузить историю выгрузок",
      );
    } finally {
      setLoading(false);
    }
  }, [accessToken, page]);

  useEffect(() => {
    void load();
  }, [load]);

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

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const canPrev = page > 1;
  const canNext = page < totalPages;

  return (
    <>
      <AppNav />
      <main className="mx-auto max-w-4xl px-4 py-8">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              Выгрузки в e-staff
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Журнал отправки резюме в систему e-staff. История поиска по HeadHunter
              находится в разделе «История».
            </p>
          </div>
          <Link
            href="/favorites"
            className="text-sm text-primary underline underline-offset-4"
          >
            К избранному
          </Link>
        </div>

        <div className="mt-6 flex items-center justify-between gap-4">
          <p className="text-sm text-muted-foreground">
            Всего записей: {loading ? "…" : total}
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!canPrev || loading}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              Назад
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!canNext || loading}
              onClick={() => setPage((p) => p + 1)}
            >
              Вперёд
            </Button>
          </div>
        </div>

        {error ? (
          <p className="mt-4 text-sm text-destructive">{sanitizeApiErrorMessage(error)}</p>
        ) : null}

        <ul className="mt-6 divide-y rounded-md border border-border">
          {loading ? (
            <li className="p-4">
              <Skeleton className="h-16 w-full" />
            </li>
          ) : items.length === 0 ? (
            <li className="p-6 text-sm text-muted-foreground">
              Пока нет выгрузок. Запустите выгрузку из карточки кандидата или из
              избранного.
            </li>
          ) : (
            items.map((row) => {
              const stage = stageLabel(row.error_stage);
              const hhUrl = hhResumePublicUrl(row.hh_resume_id);
              const cid = row.candidate_id;
              return (
              <li key={row.id} className="p-4 text-sm">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-medium">
                    {hhUrl ? (
                      <>
                        Резюме HH:{" "}
                        <a
                          href={hhUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="font-mono text-xs font-normal text-primary underline underline-offset-2 hover:opacity-90"
                        >
                          {row.hh_resume_id}
                        </a>
                      </>
                    ) : (
                      <>
                        Идентификатор кандидата:{" "}
                        <span className="font-mono text-xs font-normal">{cid}</span>
                      </>
                    )}
                  </span>
                  <span
                    className={
                      row.status === "success"
                        ? "text-emerald-600 dark:text-emerald-400"
                        : row.status === "error"
                          ? "text-destructive"
                          : "text-muted-foreground"
                    }
                  >
                    {row.status === "success"
                      ? "Успех"
                      : row.status === "error"
                        ? "Ошибка"
                        : row.status}
                  </span>
                </div>
                {row.estaff_candidate_id ? (
                  <p className="mt-1 text-muted-foreground">
                    Кандидат e-staff:{" "}
                    <span className="font-mono text-xs">{row.estaff_candidate_id}</span>
                  </p>
                ) : null}
                {row.error_message ? (
                  <p className="mt-2 text-destructive">
                    {sanitizeApiErrorMessage(row.error_message)}
                    {stage ? ` (${stage})` : ""}
                  </p>
                ) : null}
                {row.preparation_warnings && row.preparation_warnings.length > 0 ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Предупреждения: {row.preparation_warnings.join(" · ")}
                  </p>
                ) : null}
                <p className="mt-2 text-xs text-muted-foreground">
                  Создано: {formatWhen(row.created_at)}
                  {row.exported_at ? ` · Выгружено: ${formatWhen(row.exported_at)}` : ""}
                </p>
              </li>
              );
            })
          )}
        </ul>
      </main>
    </>
  );
}
