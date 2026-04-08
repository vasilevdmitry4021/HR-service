"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { History } from "lucide-react";

import { AppNav } from "@/components/AppNav";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, fetchSearchHistory } from "@/lib/api";
import { HR_SEARCH_REPEAT_KEY } from "@/lib/repeat-search";
import type { SearchHistoryRow } from "@/lib/types";
import { useAuthStore } from "@/stores/auth-store";

const PAGE_SIZE = 20;

function formatWhen(iso: string) {
  try {
    return new Intl.DateTimeFormat("ru-RU", {
      dateStyle: "short",
      timeStyle: "short",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

export default function HistoryPage() {
  const router = useRouter();
  const accessToken = useAuthStore((s) => s.accessToken);
  const hasHydrated = useAuthStore((s) => s._hasHydrated);
  const [skip, setSkip] = useState(0);
  const [total, setTotal] = useState(0);
  const [items, setItems] = useState<SearchHistoryRow[]>([]);
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
      const data = await fetchSearchHistory(skip, PAGE_SIZE);
      setItems(data.items);
      setTotal(data.total);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось загрузить историю");
    } finally {
      setLoading(false);
    }
  }, [accessToken, skip]);

  useEffect(() => {
    void load();
  }, [load]);

  const repeatSearch = useCallback(
    (row: SearchHistoryRow) => {
      const payload = {
        query: row.query,
        filters: row.filters,
      };
      sessionStorage.setItem(HR_SEARCH_REPEAT_KEY, JSON.stringify(payload));
      router.push("/search?repeat=1");
    },
    [router],
  );

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

  const canPrev = skip > 0;
  const canNext = skip + items.length < total;

  return (
    <>
      <AppNav />
      <main className="mx-auto max-w-4xl px-4 py-8 pb-20 md:pb-8">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <h1 className="text-2xl font-semibold tracking-tight">История поиска</h1>
          <Link
            href="/search"
            className="text-sm text-primary underline underline-offset-4"
          >
            К поиску
          </Link>
        </div>

        <p className="mt-2 text-sm text-muted-foreground">
          Каждый успешный поиск сохраняется. Нажмите «Повторить», чтобы открыть тот же запрос и
          фильтры на странице поиска.
        </p>

        {error && (
          <p className="mt-4 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        )}

        <div className="mt-6 overflow-x-auto rounded-lg border">
          <table className="w-full text-left text-sm">
            <thead className="border-b bg-muted/50">
              <tr>
                <th className="px-3 py-2 font-medium">Когда</th>
                <th className="px-3 py-2 font-medium">Запрос</th>
                <th className="px-3 py-2 font-medium text-right">Найдено</th>
                <th className="px-3 py-2 font-medium text-right">Действие</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 6 }, (_, i) => (
                  <tr key={i} className="border-b last:border-0">
                    <td className="px-3 py-3">
                      <Skeleton className="h-4 w-28" />
                    </td>
                    <td className="px-3 py-3">
                      <Skeleton className="h-4 w-full max-w-md" />
                    </td>
                    <td className="px-3 py-3 text-right">
                      <Skeleton className="ml-auto h-4 w-8" />
                    </td>
                    <td className="px-3 py-3 text-right">
                      <Skeleton className="ml-auto h-8 w-24" />
                    </td>
                  </tr>
                ))
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={4} className="p-0">
                    <div className="py-12">
                      <EmptyState
                        icon={<History className="h-8 w-8" />}
                        title="История пуста"
                        description="Здесь будут отображаться ваши прошлые поисковые запросы"
                        action={
                          <Link href="/search">
                            <Button>Выполнить первый поиск</Button>
                          </Link>
                        }
                      />
                    </div>
                  </td>
                </tr>
              ) : (
                items.map((row) => (
                  <tr key={row.id} className="border-b last:border-0">
                    <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                      {formatWhen(row.created_at)}
                    </td>
                    <td className="max-w-[min(28rem,50vw)] px-3 py-2">
                      <span className="line-clamp-2" title={row.query}>
                        {row.query}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">
                      {row.found}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => repeatSearch(row)}
                      >
                        Повторить
                      </Button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {!loading && total > PAGE_SIZE && (
          <div className="mt-4 flex items-center justify-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!canPrev}
              onClick={() => setSkip((s) => Math.max(0, s - PAGE_SIZE))}
            >
              Назад
            </Button>
            <span className="text-xs text-muted-foreground tabular-nums">
              {skip + 1}–{skip + items.length} из {total}
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!canNext}
              onClick={() => setSkip((s) => s + PAGE_SIZE)}
            >
              Вперёд
            </Button>
          </div>
        )}
      </main>
    </>
  );
}
