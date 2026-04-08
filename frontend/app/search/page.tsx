"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { ActiveFiltersSummary } from "@/components/search/ActiveFiltersSummary";
import { AppNav } from "@/components/AppNav";
import { CandidateList } from "@/components/search/CandidateList";
import { useEstaffExportStatusMap } from "@/hooks/useEstaffExportStatusMap";
import { FilterPanel } from "@/components/search/FilterPanel";
import { ParsedTags } from "@/components/search/ParsedTags";
import { SearchInput } from "@/components/search/SearchInput";
import { TemplatesPanel } from "@/components/search/TemplatesPanel";
import { StatusIndicator } from "@/components/StatusIndicator";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import {
  addFavorite,
  analyzeCandidate,
  analyzeSearchSnapshot,
  ApiError,
  apiFetch,
  createTemplate,
  deleteTemplate,
  evaluateSearchSnapshot,
  fetchFavorites,
  fetchReferenceAreasRussia,
  fetchTelegramStatus,
  fetchTemplates,
  removeFavorite,
} from "@/lib/api";
import { consumeRepeatSearchPayload } from "@/lib/repeat-search";
import {
  clearSearchState,
  readSearchState,
  saveSearchState,
  type ResultTab,
} from "@/lib/search-state";
import {
  emptySearchFilters,
  FALLBACK_AREA_OPTIONS,
  filtersFromApiPayload,
  filtersToApiPayload,
  hasAnyFilters,
  queryBaseWithoutFilterLine,
  type HhAreaOption,
  type SearchFiltersState,
} from "@/lib/search-filters";
import {
  LIST_SORT_OPTIONS,
  processCandidatesForList,
  type ListSortKind,
} from "@/lib/search-results-list";
import { cn } from "@/lib/utils";
import type {
  Candidate,
  ParsedParams,
  SearchResponse,
  SearchTemplateRow,
} from "@/lib/types";
import { useAuthStore } from "@/stores/auth-store";

function cardModelScore(c: Candidate): number | null {
  const fromAnalysis = c.llm_analysis?.llm_score;
  if (fromAnalysis != null) return fromAnalysis;
  return c.llm_score ?? null;
}

function SearchPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const accessToken = useAuthStore((s) => s.accessToken);
  const hasHydrated = useAuthStore((s) => s._hasHydrated);

  const [q, setQ] = useState("");
  const [filters, setFilters] = useState(emptySearchFilters());
  const [loading, setLoading] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [templates, setTemplates] = useState<SearchTemplateRow[]>([]);
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [templateSaving, setTemplateSaving] = useState(false);
  const [parsePreview, setParsePreview] = useState<{
    params: ParsedParams;
    confidence: number;
  } | null>(null);
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [activeTab, setActiveTab] = useState<ResultTab>("all");
  const [templatesPanelOpen, setTemplatesPanelOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [favMap, setFavMap] = useState<Record<string, string>>({});
  const [favBusy, setFavBusy] = useState<string | null>(null);
  const [analyzeBusy, setAnalyzeBusy] = useState<string | null>(null);
  const [snapshotEvalBusy, setSnapshotEvalBusy] = useState(false);
  const [snapshotAnalyzeBusy, setSnapshotAnalyzeBusy] = useState(false);
  const [perPage, setPerPage] = useState(20);
  const [sourceScope, setSourceScope] = useState<"hh" | "telegram" | "all">(
    "hh",
  );
  const [telegramFeatureOn, setTelegramFeatureOn] = useState(false);
  const [listFilter, setListFilter] = useState("");
  const [listSort, setListSort] = useState<ListSortKind>("server");
  const [hhAreas, setHhAreas] = useState<HhAreaOption[]>(FALLBACK_AREA_OPTIONS);
  const [hhAreasLoading, setHhAreasLoading] = useState(true);
  const [hhAreasHint, setHhAreasHint] = useState<string | null>(null);
  const repeatAppliedRef = useRef(false);

  const areaLabels = useMemo(() => {
    const m = new Map<number, string>();
    for (const a of hhAreas) m.set(a.id, a.name);
    return m;
  }, [hhAreas]);

  useEffect(() => {
    if (!accessToken) return;
    let cancelled = false;
    setHhAreasLoading(true);
    setHhAreasHint(null);
    void fetchReferenceAreasRussia()
      .then((items) => {
        if (cancelled) return;
        if (items.length > 0) {
          setHhAreas(items);
        } else {
          setHhAreas(FALLBACK_AREA_OPTIONS);
          setHhAreasHint("Справочник регионов пуст. Используется короткий список.");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setHhAreas(FALLBACK_AREA_OPTIONS);
          setHhAreasHint(
            "Справочник регионов с HeadHunter недоступен. Используется короткий список городов.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setHhAreasLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  useEffect(() => {
    if (!hasHydrated) return;
    if (!accessToken) router.replace("/login");
  }, [hasHydrated, accessToken, router]);

  useLayoutEffect(() => {
    if (!accessToken) return;
    const isRepeat = searchParams.get("repeat") === "1";
    if (isRepeat) {
      const repeat = consumeRepeatSearchPayload();
      if (repeat) {
        const f = filtersFromApiPayload(repeat.filters ?? undefined);
        setFilters(f);
        if (repeat.query.trim()) {
          setQ(repeat.query.trim());
        }
        setResults(null);
        setParsePreview(null);
        setListFilter("");
        setListSort("server");
        repeatAppliedRef.current = true;
      }
      router.replace("/search", { scroll: false });
      return;
    }
    if (repeatAppliedRef.current) {
      repeatAppliedRef.current = false;
      return;
    }
    const saved = readSearchState();
    if (!saved) return;
    setQ(saved.query);
    setFilters(filtersFromApiPayload(saved.filters ?? undefined));
    setResults(saved.results);
    setActiveTab(saved.activeTab);
    setParsePreview(null);
    setListFilter(saved.listFilter ?? "");
    setListSort(saved.listSort ?? "server");
    setPerPage(
      saved.perPage ??
        (saved.results?.per_page === 50 ? 50 : 20),
    );
  }, [accessToken, searchParams, router]);

  useEffect(() => {
    if (!accessToken) return;
    const t = window.setTimeout(() => {
      saveSearchState({
        query: q,
        filters: filtersToApiPayload(filters) ?? null,
        results,
        snapshotId: results?.snapshot_id ?? null,
        activeTab,
        listFilter,
        listSort,
        perPage,
      });
    }, 300);
    return () => window.clearTimeout(t);
  }, [accessToken, q, filters, results, activeTab, listFilter, listSort, perPage]);

  const loadTemplates = useCallback(async () => {
    if (!accessToken) return;
    try {
      const rows = await fetchTemplates();
      setTemplates(rows);
    } catch {
      /* ignore */
    }
  }, [accessToken]);

  useEffect(() => {
    void loadTemplates();
  }, [loadTemplates]);

  const refreshFavorites = useCallback(async () => {
    if (!accessToken) return;
    try {
      const rows = await fetchFavorites();
      const m: Record<string, string> = {};
      for (const f of rows) {
        const hr = f.hh_resume_id?.trim();
        if (hr) m[hr] = f.id;
        if (f.candidate_id) m[f.candidate_id] = f.id;
      }
      setFavMap(m);
    } catch {
      /* ignore */
    }
  }, [accessToken]);

  useEffect(() => {
    void refreshFavorites();
  }, [refreshFavorites]);

  useEffect(() => {
    if (!accessToken) return;
    void fetchTelegramStatus()
      .then((s) => {
        setTelegramFeatureOn(s.feature_enabled);
        if (!s.feature_enabled) setSourceScope("hh");
      })
      .catch(() => {
        setTelegramFeatureOn(false);
        setSourceScope("hh");
      });
  }, [accessToken]);

  const queryForApi = queryBaseWithoutFilterLine(q);

  const processedItems = useMemo(() => {
    const items = results?.items ?? [];
    return processCandidatesForList(items, listFilter, listSort);
  }, [results, listFilter, listSort]);

  const tabCounts = useMemo(() => {
    const items = processedItems;
    return {
      all: items.length,
      relevant: items.filter((c) => c.llm_analysis?.is_relevant === true).length,
      strong: items.filter((c) => (cardModelScore(c) ?? -1) >= 80).length,
      good: items.filter((c) => {
        const s = cardModelScore(c);
        return s != null && s >= 60 && s < 80;
      }).length,
    };
  }, [processedItems]);

  const filteredItems = useMemo(() => {
    const items = processedItems;
    switch (activeTab) {
      case "all":
        return items;
      case "relevant":
        return items.filter((c) => c.llm_analysis?.is_relevant === true);
      case "strong":
        return items.filter((c) => (cardModelScore(c) ?? -1) >= 80);
      case "good":
        return items.filter((c) => {
          const s = cardModelScore(c);
          return s != null && s >= 60 && s < 80;
        });
      default:
        return items;
    }
  }, [processedItems, activeTab]);

  const estaffBatchResumeIds = useMemo(
    () =>
      filteredItems
        .map((c) => (c.hh_resume_id || c.id).trim())
        .filter((s) => s.length > 0),
    [filteredItems],
  );
  const {
    map: estaffLatestByResumeId,
    refetch: refetchEstaffLatestMap,
  } = useEstaffExportStatusMap(estaffBatchResumeIds);

  const handleQueryChange = useCallback((value: string) => {
    setQ(value);
  }, []);

  const handleClearSearch = useCallback(() => {
    setQ("");
    setFilters(emptySearchFilters());
    setResults(null);
    setParsePreview(null);
    setActiveTab("all");
    setError(null);
    setPerPage(20);
    setListFilter("");
    setListSort("server");
    clearSearchState();
  }, []);

  const showClear = Boolean(
    q.trim() || hasAnyFilters(filters) || results,
  );

  const handleFiltersChange = useCallback((next: SearchFiltersState) => {
    setFilters(next);
  }, []);

  const fetchResultsPage = useCallback(
    async (
      page: number,
      perPageArg: number,
      snapshotIdForPaging?: string | null,
    ) => {
      const payload = filtersToApiPayload(filters);
      const body: Record<string, unknown> = {
        query: queryForApi,
        page,
        per_page: perPageArg,
        source_scope: sourceScope,
      };
      if (payload) body.filters = payload;
      if (snapshotIdForPaging && snapshotIdForPaging.trim()) {
        body.snapshot_id = snapshotIdForPaging.trim();
      }
      return apiFetch<SearchResponse>("/search", {
        method: "POST",
        body: JSON.stringify(body),
      });
    },
    [queryForApi, filters, sourceScope],
  );

  const runParseOnly = useCallback(async () => {
    if (!queryForApi.trim()) return;
    setParsing(true);
    setError(null);
    try {
      const data = await apiFetch<{
        parsed_params: ParsedParams;
        confidence: number;
      }>("/search/parse", {
        method: "POST",
        body: JSON.stringify({
          query: queryForApi,
          force_reparse: true,
        }),
      });
      setParsePreview({
        params: data.parsed_params,
        confidence: data.confidence,
      });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Ошибка разбора запроса");
    } finally {
      setParsing(false);
    }
  }, [queryForApi]);

  const runSearch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchResultsPage(0, perPage);
      setActiveTab("all");
      setResults(data);
      setParsePreview(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Ошибка поиска");
    } finally {
      setLoading(false);
    }
  }, [fetchResultsPage, perPage]);

  const goToResultsPage = useCallback(
    async (page: number) => {
      setLoading(true);
      setError(null);
      try {
        const sid =
          typeof results?.snapshot_id === "string" && results.snapshot_id.trim()
            ? results.snapshot_id.trim()
            : null;
        if (page > 0 && !sid) {
          setError(
            "Нет сохранённой выдачи для перехода на страницу. Нажмите «Найти» снова.",
          );
          return;
        }
        const data = await fetchResultsPage(
          page,
          perPage,
          sid ?? undefined,
        );
        setResults(data);
      } catch (e) {
        if (e instanceof ApiError && (e.status === 410 || e.status === 404)) {
          setResults(null);
        }
        setError(e instanceof ApiError ? e.message : "Ошибка поиска");
      } finally {
        setLoading(false);
      }
    },
    [fetchResultsPage, perPage, results?.snapshot_id],
  );

  const toggleFavorite = useCallback(
    async (c: Candidate) => {
      const rid = c.hh_resume_id || c.id;
      const existing = favMap[rid];
      setFavBusy(rid);
      setError(null);
      try {
        if (existing) {
          await removeFavorite(existing);
        } else {
          await addFavorite(c);
        }
        await refreshFavorites();
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Избранное: ошибка");
      } finally {
        setFavBusy(null);
      }
    },
    [favMap, refreshFavorites],
  );

  const refreshCurrentResultsPage = useCallback(async () => {
    if (!results) return;
    const sid =
      typeof results.snapshot_id === "string" && results.snapshot_id.trim()
        ? results.snapshot_id.trim()
        : null;
    if (!sid) return;
    setLoading(true);
    setError(null);
    try {
      const data = await fetchResultsPage(results.page, perPage, sid);
      setResults(data);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Ошибка обновления выдачи");
    } finally {
      setLoading(false);
    }
  }, [results, perPage, fetchResultsPage]);

  const handleEvaluateSnapshot = useCallback(async () => {
    const sid = results?.snapshot_id?.trim();
    if (!sid) return;
    setSnapshotEvalBusy(true);
    setError(null);
    try {
      await evaluateSearchSnapshot(sid);
      await refreshCurrentResultsPage();
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Не удалось оценить выдачу",
      );
    } finally {
      setSnapshotEvalBusy(false);
    }
  }, [results?.snapshot_id, refreshCurrentResultsPage]);

  const handleAnalyzeSnapshot = useCallback(async () => {
    const sid = results?.snapshot_id?.trim();
    if (!sid) return;
    setSnapshotAnalyzeBusy(true);
    setError(null);
    try {
      await analyzeSearchSnapshot(sid, 15);
      await refreshCurrentResultsPage();
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Не удалось выполнить детальный анализ",
      );
    } finally {
      setSnapshotAnalyzeBusy(false);
    }
  }, [results?.snapshot_id, refreshCurrentResultsPage]);

  const handleAnalyze = useCallback(
    async (c: Candidate) => {
      const rid = c.hh_resume_id || c.id;
      const q = queryForApi.trim();
      if (!q) {
        setError("Укажите поисковый запрос, чтобы оценить резюме с помощью ИИ.");
        return;
      }
      setAnalyzeBusy(rid);
      setError(null);
      try {
        const llm = await analyzeCandidate(rid, q);
        setResults((prev) => {
          if (!prev) return prev;
          const items = prev.items.map((item) => {
            const iid = item.hh_resume_id || item.id;
            if (iid !== rid) return item;
            return { ...item, llm_analysis: llm };
          });
          return { ...prev, items };
        });
      } catch (e) {
        setError(
          e instanceof ApiError
            ? e.message
            : "Не удалось выполнить оценку с помощью ИИ",
        );
      } finally {
        setAnalyzeBusy(null);
      }
    },
    [queryForApi],
  );

  const applyTemplate = useCallback((t: SearchTemplateRow) => {
    const f = filtersFromApiPayload(t.filters ?? undefined);
    setFilters(f);
    setQ(t.query.trim() || "");
    setResults(null);
    setParsePreview(null);
    setError(null);
    setListFilter("");
    setListSort("server");
  }, []);

  const removeTemplate = useCallback(
    async (id: string) => {
      setError(null);
      try {
        await deleteTemplate(id);
        await loadTemplates();
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Не удалось удалить шаблон");
      }
    },
    [loadTemplates],
  );

  const hasSearchCriteria = Boolean(
    queryForApi.trim() || hasAnyFilters(filters),
  );

  const handlePerPageChange = useCallback(
    (next: 20 | 50) => {
      if (next === perPage) return;
      setPerPage(next);
      const canRefetch =
        results != null &&
        Boolean(queryForApi.trim() || hasAnyFilters(filters));
      if (canRefetch) {
        void (async () => {
          setLoading(true);
          setError(null);
          try {
            const sid =
              typeof results.snapshot_id === "string" &&
              results.snapshot_id.trim()
                ? results.snapshot_id.trim()
                : null;
            const data = await fetchResultsPage(0, next, sid ?? undefined);
            setActiveTab("all");
            setResults(data);
          } catch (e) {
            if (e instanceof ApiError && (e.status === 410 || e.status === 404)) {
              setResults(null);
            }
            setError(e instanceof ApiError ? e.message : "Ошибка поиска");
          } finally {
            setLoading(false);
          }
        })();
      }
    },
    [perPage, results, filters, queryForApi, fetchResultsPage],
  );

  const submitSaveTemplate = useCallback(async () => {
    const name = templateName.trim();
    const hasCriteria = queryForApi.trim() || hasAnyFilters(filters);
    if (!name || !hasCriteria) return;
    setTemplateSaving(true);
    setError(null);
    try {
      const payload = filtersToApiPayload(filters);
      await createTemplate(name, queryForApi, payload);
      setSaveDialogOpen(false);
      setTemplateName("");
      await loadTemplates();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось сохранить шаблон");
    } finally {
      setTemplateSaving(false);
    }
  }, [templateName, queryForApi, filters, loadTemplates]);

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

  const pagination =
    results != null && results.found > 0
      ? {
          show:
            results.pages > 1 || results.found > results.per_page,
          pageIndex: results.page,
          totalPages: Math.max(results.pages, 1),
          rangeStart: results.page * results.per_page + 1,
          rangeEnd: results.page * results.per_page + results.items.length,
          canPrev: results.page > 0,
          canNext: results.pages > 0 && results.page < results.pages - 1,
        }
      : null;

  const selectFieldClass =
    "select-chevron h-9 rounded-md border border-input bg-background pl-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

  return (
    <>
      <AppNav />
      <main className="mx-auto max-w-7xl px-4 py-6 lg:px-6 lg:py-10">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between mb-8">
          <h1 className="text-3xl font-display font-bold tracking-tight">Поиск кандидатов</h1>
          <StatusIndicator />
        </div>

        <div className="flex flex-col gap-8 lg:flex-row lg:items-start lg:gap-10">
          <div className="min-w-0 flex-1 space-y-8">
            <div className="flex flex-col gap-3">
              <SearchInput
                value={q}
                onChange={handleQueryChange}
                onSubmit={runSearch}
                loading={loading}
                parsing={parsing}
                placeholder="Найдите кандидата по запросу: должность, навыки, город..."
                onClear={handleClearSearch}
                showClear={showClear}
              />
              <ActiveFiltersSummary
                filters={filters}
                areaLabels={areaLabels}
                parsedRegion={
                  (results?.parsed_params?.region ??
                    parsePreview?.params?.region) as string | undefined
                }
              />
              {telegramFeatureOn ? (
                <div className="flex flex-wrap items-center gap-2">
                  <Label htmlFor="search-source-scope" className="text-sm shrink-0">
                    Источник данных
                  </Label>
                  <select
                    id="search-source-scope"
                    className={selectFieldClass}
                    value={sourceScope}
                    onChange={(e) =>
                      setSourceScope(
                        e.target.value as "hh" | "telegram" | "all",
                      )
                    }
                    disabled={loading}
                  >
                    <option value="hh">HeadHunter</option>
                    <option value="telegram">Telegram</option>
                    <option value="all">Все источники</option>
                  </select>
                </div>
              ) : null}
              <button
                type="button"
                onClick={() => void runParseOnly()}
                disabled={!queryForApi.trim() || parsing || loading}
                className="self-start text-sm text-primary underline disabled:pointer-events-none disabled:opacity-50"
              >
                Только разобрать запрос
              </button>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => setTemplatesPanelOpen(true)}
              >
                Шаблоны поиска ({templates.length})
              </Button>
            </div>

            {error && (
              <div className="rounded-lg border-2 border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive animate-fade-in">
                <p className="font-medium">Произошла ошибка</p>
                <p className="mt-1 text-xs">{error}</p>
              </div>
            )}

            {results != null &&
              results.found > 0 &&
              results.snapshot_id &&
              results.snapshot_id.trim() && (
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    disabled={snapshotEvalBusy || loading}
                    onClick={() => void handleEvaluateSnapshot()}
                  >
                    {snapshotEvalBusy ? "Оценка выдачи…" : "Оценить выдачу"}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={snapshotAnalyzeBusy || loading}
                    onClick={() => void handleAnalyzeSnapshot()}
                  >
                    {snapshotAnalyzeBusy
                      ? "Детальный анализ…"
                      : "Детальный анализ (топ-15)"}
                  </Button>
                </div>
              )}

            <section className="space-y-3">
              <h2 className="text-sm font-display font-semibold text-foreground/80">
                Распознанные параметры
              </h2>
              <ParsedTags
                params={results?.parsed_params ?? parsePreview?.params ?? null}
                confidence={
                  results ? null : (parsePreview?.confidence ?? null)
                }
              />
            </section>

            <section className="space-y-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <h2 className="text-lg font-display font-semibold text-foreground">
                  Результаты поиска
                </h2>
                {results != null && (
                  <div
                    className="flex flex-wrap gap-2"
                    role="tablist"
                    aria-label="Фильтр по оценке"
                  >
                    {(
                      [
                        ["all", "Все", tabCounts.all] as const,
                        ["relevant", "Релевантные", tabCounts.relevant] as const,
                        ["strong", "Отличные", tabCounts.strong] as const,
                        ["good", "Хорошие", tabCounts.good] as const,
                      ] as const
                    ).map(([id, label, count]) => (
                      <button
                        key={id}
                        type="button"
                        role="tab"
                        aria-selected={activeTab === id}
                        className={cn(
                          "rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
                          activeTab === id
                            ? "border-primary bg-primary text-primary-foreground"
                            : "border-transparent bg-muted/60 text-muted-foreground hover:bg-muted",
                        )}
                        onClick={() => setActiveTab(id)}
                      >
                        {label} ({count})
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {results != null && results.found > 0 && (
                <div className="space-y-4 rounded-xl border-2 bg-muted/30 p-5">
                  <div className="grid grid-cols-1 gap-5 md:grid-cols-2 md:gap-x-8 md:gap-y-5 xl:grid-cols-12 xl:gap-x-6">
                    <div className="min-w-0 space-y-2 xl:col-span-5">
                      <Label
                        htmlFor="list-filter"
                        className="block text-xs font-medium text-muted-foreground"
                      >
                        На этой странице
                      </Label>
                      <Input
                        id="list-filter"
                        value={listFilter}
                        onChange={(e) => setListFilter(e.target.value)}
                        placeholder="ФИО, должность, навыки…"
                        className="h-9 w-full"
                      />
                    </div>
                    <div className="min-w-0 space-y-2 xl:col-span-3">
                      <Label
                        htmlFor="per-page"
                        className="block text-xs font-medium text-muted-foreground"
                      >
                        Размер страницы
                      </Label>
                      <select
                        id="per-page"
                        className={cn(selectFieldClass, "w-full min-w-0")}
                        value={perPage}
                        onChange={(e) =>
                          handlePerPageChange(
                            Number(e.target.value) === 50 ? 50 : 20,
                          )
                        }
                      >
                        <option value={20}>20 резюме</option>
                        <option value={50}>50 резюме</option>
                      </select>
                    </div>
                    <div className="min-w-0 space-y-2 md:col-span-2 xl:col-span-4">
                      <Label
                        htmlFor="list-sort"
                        className="block text-xs font-medium text-muted-foreground"
                      >
                        Сортировка
                      </Label>
                      <select
                        id="list-sort"
                        className={cn(selectFieldClass, "w-full min-w-0")}
                        value={listSort}
                        onChange={(e) =>
                          setListSort(e.target.value as ListSortKind)
                        }
                      >
                        {LIST_SORT_OPTIONS.map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    Локальный поиск и сортировка ниже относятся к текущей
                    странице списка. Порядок выдачи по всему снимку поиска
                    задаётся на сервере при нажатии «Найти».
                  </p>
                </div>
              )}

              {!loading &&
              results != null &&
              results.items.length > 0 &&
              filteredItems.length === 0 ? (
                <p className="rounded-lg border border-dashed bg-muted/30 px-4 py-8 text-center text-sm text-muted-foreground">
                  {processedItems.length === 0
                    ? "На этой странице нет совпадений с локальным поиском. Измените текст фильтра или перейдите на другую страницу выдачи."
                    : "В выбранной категории нет резюме. Выберите другую вкладку или «Все»."}
                </p>
              ) : (
                <CandidateList
                  items={filteredItems}
                  searchQuery={queryForApi}
                  favoriteByResumeId={favMap}
                  favoriteBusyResumeId={favBusy}
                  onToggleFavorite={toggleFavorite}
                  onAnalyze={handleAnalyze}
                  analyzeBusyResumeId={analyzeBusy}
                  showEmptyGuidance={results != null && results.found === 0}
                  loading={loading}
                  estaffLatestByResumeId={estaffLatestByResumeId}
                  onEstaffExportUpdated={() => void refetchEstaffLatestMap()}
                />
              )}

              {pagination?.show && !loading && (
                <div className="space-y-3">
                  <div className="flex justify-center">
                    <div className="inline-flex items-center gap-2 rounded-lg bg-muted/30 px-4 py-2 text-sm">
                      <span className="text-muted-foreground">Показано</span>
                      <span className="font-medium tabular-nums text-foreground">
                        {pagination.rangeStart}–{pagination.rangeEnd}
                      </span>
                      <span className="text-muted-foreground">из</span>
                      <span className="font-medium tabular-nums text-foreground">
                        {results!.found}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center justify-center gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={!pagination.canPrev || loading}
                      onClick={() =>
                        void goToResultsPage(pagination.pageIndex - 1)
                      }
                    >
                      Назад
                    </Button>
                    {Array.from({ length: Math.min(pagination.totalPages, 5) }, (_, i) => {
                      const page = i;
                      return (
                        <Button
                          key={page}
                          type="button"
                          variant={pagination.pageIndex === page ? "default" : "outline"}
                          size="sm"
                          onClick={() => void goToResultsPage(page)}
                        >
                          {page + 1}
                        </Button>
                      );
                    })}
                    {pagination.totalPages > 5 && (
                      <span className="text-muted-foreground">...</span>
                    )}
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={!pagination.canNext || loading}
                      onClick={() =>
                        void goToResultsPage(pagination.pageIndex + 1)
                      }
                    >
                      Вперёд
                    </Button>
                  </div>
                </div>
              )}
            </section>

            <div className="mt-12 flex justify-center gap-4 text-sm text-muted-foreground pb-20 md:pb-0">
              <Link href="/history" className="hover:text-primary transition-colors">
                История поиска
              </Link>
              <span className="text-border">|</span>
              <Link href="/settings" className="hover:text-primary transition-colors">
                Настройки
              </Link>
            </div>
          </div>

          <FilterPanel
            value={filters}
            onChange={handleFiltersChange}
            areas={hhAreas}
            areasLoading={hhAreasLoading}
            areasHint={hhAreasHint}
          />
        </div>

        <Sheet open={templatesPanelOpen} onOpenChange={setTemplatesPanelOpen}>
          <SheetContent className="max-w-lg">
            <TemplatesPanel
              templates={templates}
              canSave={hasSearchCriteria}
              onSaveCurrent={() => {
                setTemplateName("");
                setSaveDialogOpen(true);
              }}
              onApply={(t) => {
                applyTemplate(t);
                setTemplatesPanelOpen(false);
              }}
              onDelete={removeTemplate}
            />
          </SheetContent>
        </Sheet>

        {saveDialogOpen && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
            role="presentation"
            onClick={() => !templateSaving && setSaveDialogOpen(false)}
          >
            <div
              role="dialog"
              aria-labelledby="save-template-title"
              className="w-full max-w-md rounded-lg border bg-background p-4 shadow-lg"
              onClick={(e) => e.stopPropagation()}
            >
              <h2 id="save-template-title" className="text-lg font-semibold">
                Сохранить шаблон
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Будут сохранены текущий текст запроса и фильтры из панели справа.
              </p>
              <div className="mt-4 space-y-2">
                <label htmlFor="tpl-name" className="text-sm font-medium">
                  Название
                </label>
                <Input
                  id="tpl-name"
                  value={templateName}
                  onChange={(e) => setTemplateName(e.target.value)}
                  placeholder="Например: Java Москва"
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void submitSaveTemplate();
                  }}
                />
              </div>
              <div className="mt-4 flex justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={templateSaving}
                  onClick={() => setSaveDialogOpen(false)}
                >
                  Отмена
                </Button>
                <Button
                  type="button"
                  disabled={templateSaving || !templateName.trim()}
                  onClick={() => void submitSaveTemplate()}
                >
                  {templateSaving ? "Сохранение…" : "Сохранить"}
                </Button>
              </div>
            </div>
          </div>
        )}
      </main>
    </>
  );
}

export default function SearchPage() {
  return (
    <Suspense
      fallback={
        <>
          <AppNav />
          <main className="flex min-h-screen items-center justify-center p-4">
            <p className="text-muted-foreground">Загрузка…</p>
          </main>
        </>
      }
    >
      <SearchPageContent />
    </Suspense>
  );
}
