"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Heart } from "lucide-react";

import { FavoriteCard } from "@/components/favorites/FavoriteCard";
import { useEstaffExportStatusMap } from "@/hooks/useEstaffExportStatusMap";
import { AppNav } from "@/components/AppNav";
import { EstaffExportDialog } from "@/components/estaff/EstaffExportDialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ApiError,
  estaffLlmAnalysisHasPayload,
  fetchFavorites,
  patchFavoriteNotes,
  removeFavorite,
  type EstaffHrBundleContext,
} from "@/lib/api";
import type { FavoriteRow } from "@/lib/types";
import { useAuthStore } from "@/stores/auth-store";

const NOTES_SAVED_DISPLAY_MS = 2000;

export default function FavoritesPage() {
  const router = useRouter();
  const accessToken = useAuthStore((s) => s.accessToken);
  const hasHydrated = useAuthStore((s) => s._hasHydrated);
  const [items, setItems] = useState<FavoriteRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draftNotes, setDraftNotes] = useState<Record<string, string>>({});
  const [savingId, setSavingId] = useState<string | null>(null);
  const [notesSavedId, setNotesSavedId] = useState<string | null>(null);
  const notesSavedTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [estaffDialogOpen, setEstaffDialogOpen] = useState(false);
  const [estaffBulkResumeIds, setEstaffBulkResumeIds] = useState<string[]>([]);
  const [estaffBulkHrContext, setEstaffBulkHrContext] = useState<
    Record<string, EstaffHrBundleContext> | undefined
  >(undefined);
  const [bulkHint, setBulkHint] = useState<string | null>(null);

  const favoriteEstaffResumeIds = useMemo(
    () =>
      items
        .map((f) =>
          (f.hh_resume_id?.trim() || f.candidate_id || "").trim(),
        )
        .filter((s) => s.length > 0),
    [items],
  );
  const {
    map: estaffFavoritesMap,
    refetch: refetchEstaffFavoritesMap,
  } = useEstaffExportStatusMap(favoriteEstaffResumeIds);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = await fetchFavorites();
      setItems(rows);
      const d: Record<string, string> = {};
      for (const r of rows) d[r.id] = r.notes;
      setDraftNotes(d);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось загрузить");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!hasHydrated) return;
    if (!accessToken) {
      router.replace("/login");
      return;
    }
    void load();
  }, [hasHydrated, accessToken, load, router]);

  useEffect(
    () => () => {
      if (notesSavedTimeoutRef.current) {
        clearTimeout(notesSavedTimeoutRef.current);
      }
    },
    [],
  );

  const saveNotes = async (id: string) => {
    setSavingId(id);
    setError(null);
    try {
      const text = draftNotes[id] ?? "";
      await patchFavoriteNotes(id, text);
      setNotesSavedId(id);
      if (notesSavedTimeoutRef.current) {
        clearTimeout(notesSavedTimeoutRef.current);
      }
      notesSavedTimeoutRef.current = setTimeout(() => {
        notesSavedTimeoutRef.current = null;
        setNotesSavedId(null);
      }, NOTES_SAVED_DISPLAY_MS);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не сохранилось");
    } finally {
      setSavingId(null);
    }
  };

  const del = async (id: string) => {
    setError(null);
    try {
      await removeFavorite(id);
      setSelectedIds((prev) => {
        const n = new Set(prev);
        n.delete(id);
        return n;
      });
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось удалить");
    }
  };

  const setFavoriteSelected = (favoriteId: string, on: boolean) => {
    setSelectedIds((prev) => {
      const n = new Set(prev);
      if (on) n.add(favoriteId);
      else n.delete(favoriteId);
      return n;
    });
  };

  const openBulkEstaffDialog = () => {
    const rows = items.filter((f) => selectedIds.has(f.id));
    if (rows.length === 0) return;
    const ids = rows
      .map((f) => (f.hh_resume_id?.trim() || f.candidate_id || "").trim())
      .filter((s) => s.length > 0);
    setEstaffBulkResumeIds(ids);
    const ctx: Record<string, EstaffHrBundleContext> = {};
    for (const f of rows) {
      const key = (f.hh_resume_id?.trim() || f.candidate_id || "").trim();
      if (!key) continue;
      const row: EstaffHrBundleContext = {};
      if (
        f.llm_analysis != null &&
        estaffLlmAnalysisHasPayload(f.llm_analysis)
      ) {
        row.hr_llm_analysis = f.llm_analysis;
      }
      if (f.llm_summary?.trim()) row.hr_llm_summary = f.llm_summary;
      if (f.llm_score != null) row.hr_llm_score = f.llm_score;
      if (Object.keys(row).length) ctx[key] = row;
    }
    setEstaffBulkHrContext(Object.keys(ctx).length ? ctx : undefined);
    setEstaffDialogOpen(true);
  };

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

  return (
    <>
      <AppNav />
      <main className="mx-auto max-w-3xl space-y-6 px-4 py-8 pb-20 md:pb-8">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h1 className="text-2xl font-semibold tracking-tight">Избранное</h1>
          {selectedIds.size > 0 ? (
            <Button type="button" onClick={openBulkEstaffDialog}>
              {`Выгрузить выбранные в e-staff (${selectedIds.size})`}
            </Button>
          ) : null}
        </div>

        {bulkHint ? (
          <p className="text-sm text-muted-foreground">{bulkHint}</p>
        ) : null}

        {error && (
          <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        )}

        {loading && (
          <ul className="space-y-6" aria-busy="true" aria-label="Загрузка избранного">
            {Array.from({ length: 3 }, (_, i) => (
              <li key={i}>
                <Card>
                  <CardHeader>
                    <Skeleton className="h-6 w-48" />
                    <Skeleton className="mt-2 h-3 w-32" />
                  </CardHeader>
                  <CardContent className="space-y-2">
                    <Skeleton className="h-24 w-full" />
                    <Skeleton className="h-8 w-36" />
                  </CardContent>
                </Card>
              </li>
            ))}
          </ul>
        )}

        {!loading && items.length === 0 && (
          <EmptyState
            icon={<Heart className="h-8 w-8" />}
            title="Избранное пустое"
            description="Добавляйте интересных кандидатов в избранное, чтобы быстро находить их позже"
            action={
              <Link href="/search">
                <Button>Перейти к поиску</Button>
              </Link>
            }
          />
        )}

        <ul className="space-y-6">
          {!loading &&
            items.map((f) => (
              <li key={f.id}>
                <FavoriteCard
                  favorite={f}
                  draftNotes={draftNotes[f.id] ?? ""}
                  onNotesChange={(value) =>
                    setDraftNotes((prev) => ({ ...prev, [f.id]: value }))
                  }
                  onSaveNotes={() => void saveNotes(f.id)}
                  onRemove={() => void del(f.id)}
                  savingNotes={savingId === f.id}
                  notesSaved={notesSavedId === f.id}
                  selectionMode
                  selected={selectedIds.has(f.id)}
                  onSelectionChange={(on) => setFavoriteSelected(f.id, on)}
                  parentEstaffLatest={
                    estaffFavoritesMap[
                      (f.hh_resume_id?.trim() || f.candidate_id || "") as string
                    ] ?? null
                  }
                  onEstaffExportUpdated={() =>
                    void refetchEstaffFavoritesMap()
                  }
                  onFavoriteRefreshed={(row) => {
                    setItems((prev) =>
                      prev.map((x) => (x.id === row.id ? row : x)),
                    );
                  }}
                />
              </li>
            ))}
        </ul>

        <EstaffExportDialog
          open={estaffDialogOpen}
          onOpenChange={setEstaffDialogOpen}
          resumeIds={estaffBulkResumeIds}
          showToastNotifications={false}
          hrBundleContextByResumeId={estaffBulkHrContext}
          onSuccess={async (summary) => {
            setBulkHint(
              summary
                ? `Готово: успешно ${summary.succeeded}, с ошибкой ${summary.failed}. Подробности — в разделе «Выгрузки e-staff» или у карточек.`
                : null,
            );
            setSelectedIds(new Set());
            await load();
            void refetchEstaffFavoritesMap();
          }}
        />
      </main>
    </>
  );
}
