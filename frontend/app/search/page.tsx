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
import { CircleHelp } from "lucide-react";

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
import { Progress } from "@/components/ui/progress";
import { RadioGroup, RadioGroupItemWithLabel } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import {
  addFavorite,
  analyzeCandidate,
  ApiError,
  apiFetch,
  cancelAnalyzeSearchSnapshot,
  cancelEvaluateSearchSnapshot,
  createTemplate,
  fetchAnalyzeSearchProgress,
  deleteTemplate,
  fetchEvaluateSearchProgress,
  fetchFavorites,
  fetchReferenceProfessionalRoles,
  fetchReferenceAreasRussia,
  fetchTemplates,
  removeFavorite,
  startAnalyzeSearchSnapshot,
  startEvaluateSearchSnapshot,
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
  type HhProfessionalRoleOption,
  type SearchFiltersState,
} from "@/lib/search-filters";
import {
  LIST_SORT_OPTIONS,
  filterCandidatesBySubstring,
  type ListSortKind,
} from "@/lib/search-results-list";
import { cn } from "@/lib/utils";
import type {
  Candidate,
  ParsedParams,
  SearchMode,
  SearchResponse,
  SearchTemplateRow,
} from "@/lib/types";
import { useAuthStore } from "@/stores/auth-store";

function cardModelScore(c: Candidate): number | null {
  const fromAnalysis = c.llm_analysis?.llm_score;
  if (fromAnalysis != null) return fromAnalysis;
  return c.llm_score ?? null;
}

function mapProgressToUi(progress: {
  status: string;
  stage: string;
  phase: string;
  total_count: number;
  scored_count: number;
  llm_scored_count?: number;
  fallback_scored_count?: number;
  coverage_ratio?: number;
  llm_coverage_ratio?: number;
  unresolved_count?: number;
  llm_only_complete?: boolean;
  interactive_done_count?: number;
  interactive_total_count?: number;
  background_done_count?: number;
  background_total_count?: number;
  interactive_fallback_count?: number;
  background_fallback_count?: number;
}) {
  const interactiveTotal = progress.interactive_total_count ?? 0;
  const interactiveDone = progress.interactive_done_count ?? 0;
  return {
    status: progress.status,
    stage: progress.stage,
    phase: progress.phase,
    total: progress.total_count,
    scored: progress.scored_count,
    llmScored: progress.llm_scored_count ?? 0,
    fallbackScored: progress.fallback_scored_count ?? 0,
    coverageRatio: progress.coverage_ratio ?? 0,
    llmCoverageRatio: progress.llm_coverage_ratio ?? progress.coverage_ratio ?? 0,
    unresolvedCount: progress.unresolved_count ?? 0,
    llmOnlyComplete: progress.llm_only_complete ?? false,
    interactiveDone,
    interactiveTotal,
    backgroundDone: progress.background_done_count ?? 0,
    backgroundTotal: progress.background_total_count ?? 0,
    interactiveFallback: progress.interactive_fallback_count ?? 0,
    backgroundFallback: progress.background_fallback_count ?? 0,
    interactiveReady:
      interactiveTotal > 0
        ? interactiveDone >= interactiveTotal
        : progress.phase === "background" || progress.status === "done" || progress.status === "partial",
  };
}

function statusLabelRu(status: string): string {
  switch (status) {
    case "done":
      return "Завершено";
    case "partial":
      return "Завершено частично";
    case "error":
      return "Ошибка";
    case "cancelled":
      return "Остановлено";
    case "running":
      return "Выполняется";
    case "queued":
      return "В очереди";
    default:
      return status || "Выполняется";
  }
}

function stageLabelRu(stage: string): string {
  switch (stage) {
    case "preparing":
      return "Подготавливаем резюме";
    case "evaluating_top":
      return "Оцениваем найденные резюме";
    case "evaluating_rest":
      return "Дооцениваем оставшиеся резюме";
    case "done":
      return "Оценка завершена";
    case "partial":
      return "Оценка завершена частично";
    case "error":
      return "Ошибка оценки";
    case "cancelled":
      return "Оценка остановлена";
    default:
      return "Выполняем оценку";
  }
}

function analyzeStageLabelRu(stage: string): string {
  switch (stage) {
    case "queued":
      return "Задача в очереди";
    case "preparing":
      return "Подготовка резюме";
    case "running":
      return "Детальный анализ";
    case "done":
      return "Детальный анализ завершен";
    case "error":
      return "Ошибка анализа";
    case "cancelled":
      return "Анализ остановлен";
    default:
      return "Детальный анализ";
  }
}

function SearchPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const accessToken = useAuthStore((s) => s.accessToken);
  const hasHydrated = useAuthStore((s) => s._hasHydrated);

  const [q, setQ] = useState("");
  const [searchMode, setSearchMode] = useState<SearchMode>("precise");
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
  const [snapshotAnalyzeJob, setSnapshotAnalyzeJob] = useState<{
    snapshotId: string;
    jobId: string;
  } | null>(null);
  const [snapshotAnalyzeProgress, setSnapshotAnalyzeProgress] = useState<{
    status: string;
    stage: string;
    total: number;
    processed: number;
    analyzed: number;
  } | null>(null);
  const [snapshotEvalJob, setSnapshotEvalJob] = useState<{
    snapshotId: string;
    jobId: string;
  } | null>(null);
  const [snapshotEvalProgress, setSnapshotEvalProgress] = useState<{
    status: string;
    stage: string;
    phase: string;
    total: number;
    scored: number;
    llmScored: number;
    fallbackScored: number;
    coverageRatio: number;
    llmCoverageRatio: number;
    unresolvedCount: number;
    llmOnlyComplete: boolean;
    interactiveDone: number;
    interactiveTotal: number;
    backgroundDone: number;
    backgroundTotal: number;
    interactiveFallback: number;
    backgroundFallback: number;
    interactiveReady: boolean;
  } | null>(null);
  const [snapshotEvalScores, setSnapshotEvalScores] = useState<
    Record<string, number | null>
  >({});
  const snapshotEvalPollKeyRef = useRef<string | null>(null);
  const snapshotEvalRunIdRef = useRef(0);
  const snapshotEvalInteractiveReadyRef = useRef(false);
  const snapshotAnalyzePollKeyRef = useRef<string | null>(null);
  const snapshotAnalyzeRunIdRef = useRef(0);
  const listRefetchRunIdRef = useRef(0);
  const [perPage, setPerPage] = useState(20);
  const [sourceScope] = useState<"hh">("hh");
  const [listFilter, setListFilter] = useState("");
  const [listSort, setListSort] = useState<ListSortKind>("server");
  const [hhAreas, setHhAreas] = useState<HhAreaOption[]>(FALLBACK_AREA_OPTIONS);
  const [hhAreasLoading, setHhAreasLoading] = useState(true);
  const [hhAreasHint, setHhAreasHint] = useState<string | null>(null);
  const [hhProfessionalRoles, setHhProfessionalRoles] = useState<HhProfessionalRoleOption[]>([]);
  const [hhProfessionalRolesLoading, setHhProfessionalRolesLoading] = useState(true);
  const [hhProfessionalRolesHint, setHhProfessionalRolesHint] = useState<string | null>(null);
  const repeatAppliedRef = useRef(false);
  const [evalProgressVisible, setEvalProgressVisible] = useState(true);
  const [analyzeProgressVisible, setAnalyzeProgressVisible] = useState(true);
  const evalStatus = snapshotEvalProgress?.status ?? (snapshotEvalBusy ? "running" : "");
  const evalIsActive =
    (snapshotEvalBusy || Boolean(snapshotEvalJob)) &&
    evalStatus !== "done" &&
    evalStatus !== "partial" &&
    evalStatus !== "error" &&
    evalStatus !== "cancelled";
  const evalCompleted = snapshotEvalProgress?.status === "done";
  const analyzeStatus =
    snapshotAnalyzeProgress?.status ?? (snapshotAnalyzeBusy ? "running" : "");
  const analyzeIsActive =
    (snapshotAnalyzeBusy || Boolean(snapshotAnalyzeJob)) &&
    analyzeStatus !== "done" &&
    analyzeStatus !== "error" &&
    analyzeStatus !== "cancelled";
  const batchOperationActive = evalIsActive || analyzeIsActive;
  const canShowAnalyzeTop = evalCompleted;
  const canRunEvaluate = !analyzeIsActive && !evalIsActive;
  const canRunAnalyzeTop = evalCompleted && !analyzeIsActive && !evalIsActive;

  useEffect(() => {
    if (!snapshotEvalProgress) {
      setEvalProgressVisible(false);
      return;
    }
    if (
      snapshotEvalProgress.status !== "done" &&
      snapshotEvalProgress.status !== "partial" &&
      snapshotEvalProgress.status !== "error" &&
      snapshotEvalProgress.status !== "cancelled"
    ) {
      setEvalProgressVisible(true);
      return;
    }
    const t = setTimeout(() => setEvalProgressVisible(false), 2000);
    return () => clearTimeout(t);
  }, [snapshotEvalProgress, snapshotEvalProgress?.status]);

  useEffect(() => {
    if (!snapshotAnalyzeProgress) {
      setAnalyzeProgressVisible(false);
      return;
    }
    if (
      snapshotAnalyzeProgress.status !== "done" &&
      snapshotAnalyzeProgress.status !== "error" &&
      snapshotAnalyzeProgress.status !== "cancelled"
    ) {
      setAnalyzeProgressVisible(true);
      return;
    }
    const t = setTimeout(() => setAnalyzeProgressVisible(false), 2000);
    return () => clearTimeout(t);
  }, [snapshotAnalyzeProgress, snapshotAnalyzeProgress?.status]);

  const areaLabels = useMemo(() => {
    const m = new Map<number, string>();
    for (const a of hhAreas) m.set(a.id, a.name);
    return m;
  }, [hhAreas]);
  const roleLabels = useMemo(() => {
    const m = new Map<number, string>();
    for (const role of hhProfessionalRoles) m.set(role.id, role.name);
    return m;
  }, [hhProfessionalRoles]);

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
    if (!accessToken) return;
    let cancelled = false;
    setHhProfessionalRolesLoading(true);
    setHhProfessionalRolesHint(null);
    void fetchReferenceProfessionalRoles()
      .then((items) => {
        if (cancelled) return;
        setHhProfessionalRoles(items);
      })
      .catch(() => {
        if (!cancelled) {
          setHhProfessionalRoles([]);
          setHhProfessionalRolesHint("Справочник ролей HeadHunter временно недоступен.");
        }
      })
      .finally(() => {
        if (!cancelled) setHhProfessionalRolesLoading(false);
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
    setSearchMode(saved.searchMode ?? "precise");
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
    setSnapshotEvalJob(saved.snapshotEvalJob ?? null);
    setSnapshotEvalProgress(saved.snapshotEvalProgress ?? null);
    setSnapshotAnalyzeJob(saved.snapshotAnalyzeJob ?? null);
    setSnapshotAnalyzeProgress(saved.snapshotAnalyzeProgress ?? null);
  }, [accessToken, searchParams, router]);

  useEffect(() => {
    if (!accessToken) return;
    const t = window.setTimeout(() => {
      saveSearchState({
        query: q,
        searchMode,
        filters: filtersToApiPayload(filters) ?? null,
        results,
        snapshotId: results?.snapshot_id ?? null,
        activeTab,
        listFilter,
        listSort,
        perPage,
        snapshotEvalJob,
        snapshotEvalProgress,
        snapshotAnalyzeJob,
        snapshotAnalyzeProgress,
      });
    }, 300);
    return () => window.clearTimeout(t);
  }, [
    accessToken,
    q,
    searchMode,
    filters,
    results,
    activeTab,
    listFilter,
    listSort,
    perPage,
    snapshotEvalJob,
    snapshotEvalProgress,
    snapshotAnalyzeJob,
    snapshotAnalyzeProgress,
  ]);

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

  const queryForApi = queryBaseWithoutFilterLine(q);

  const processedItems = useMemo(() => {
    const items = results?.items ?? [];
    const withOverlay =
      Object.keys(snapshotEvalScores).length === 0
        ? items
        : items.map((item) => {
            const byId = snapshotEvalScores[item.id];
            const resumeKey =
              item.hh_resume_id && item.hh_resume_id.trim()
                ? item.hh_resume_id.trim()
                : null;
            const byResumeId = resumeKey ? snapshotEvalScores[resumeKey] : undefined;
            const nextScore = byId !== undefined ? byId : byResumeId;
            if (nextScore === undefined) return item;
            return { ...item, llm_score: nextScore ?? null };
          });
    return filterCandidatesBySubstring(withOverlay, listFilter);
  }, [results, snapshotEvalScores, listFilter]);

  useEffect(() => {
    const currentSnapshotId =
      typeof results?.snapshot_id === "string" && results.snapshot_id.trim()
        ? results.snapshot_id.trim()
        : null;
    if (snapshotEvalJob && currentSnapshotId && snapshotEvalJob.snapshotId !== currentSnapshotId) {
      snapshotEvalRunIdRef.current += 1;
      setSnapshotEvalJob(null);
      setSnapshotEvalProgress(null);
      setSnapshotEvalScores({});
      setSnapshotEvalBusy(false);
    }
    if (!currentSnapshotId && snapshotEvalJob) {
      snapshotEvalRunIdRef.current += 1;
      setSnapshotEvalJob(null);
      setSnapshotEvalProgress(null);
      setSnapshotEvalScores({});
      setSnapshotEvalBusy(false);
    }
    if (
      snapshotAnalyzeJob &&
      currentSnapshotId &&
      snapshotAnalyzeJob.snapshotId !== currentSnapshotId
    ) {
      snapshotAnalyzeRunIdRef.current += 1;
      setSnapshotAnalyzeJob(null);
      setSnapshotAnalyzeProgress(null);
      setSnapshotAnalyzeBusy(false);
    }
    if (!currentSnapshotId && snapshotAnalyzeJob) {
      snapshotAnalyzeRunIdRef.current += 1;
      setSnapshotAnalyzeJob(null);
      setSnapshotAnalyzeProgress(null);
      setSnapshotAnalyzeBusy(false);
    }
  }, [results?.snapshot_id, snapshotEvalJob, snapshotAnalyzeJob]);

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
    snapshotEvalRunIdRef.current += 1;
    setQ("");
    setSearchMode("precise");
    setFilters(emptySearchFilters());
    setResults(null);
    setParsePreview(null);
    setActiveTab("all");
    setError(null);
    setPerPage(20);
    setListFilter("");
    setListSort("server");
    setSnapshotEvalJob(null);
    setSnapshotEvalProgress(null);
    setSnapshotEvalScores({});
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
      sortArg: ListSortKind = listSort,
    ) => {
      const payload = filtersToApiPayload(filters);
      const body: Record<string, unknown> = {
        query: queryForApi,
        search_mode: searchMode,
        page,
        per_page: perPageArg,
        source_scope: sourceScope,
      };
      if (sortArg !== "server") {
        body.sort_by = sortArg;
      }
      if (payload) body.filters = payload;
      if (snapshotIdForPaging && snapshotIdForPaging.trim()) {
        body.snapshot_id = snapshotIdForPaging.trim();
      }
      return apiFetch<SearchResponse>("/search", {
        method: "POST",
        body: JSON.stringify(body),
      });
    },
    [queryForApi, searchMode, filters, sourceScope, listSort],
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
    snapshotEvalRunIdRef.current += 1;
    setLoading(true);
    setError(null);
    setSnapshotEvalJob(null);
    setSnapshotEvalProgress(null);
    setSnapshotEvalScores({});
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

  const pollSnapshotEvaluation = useCallback(
    async (snapshotId: string, jobId: string) => {
      const pollKey = `${snapshotId}:${jobId}`;
      const runId = snapshotEvalRunIdRef.current;
      if (snapshotEvalPollKeyRef.current === pollKey) return;
      snapshotEvalPollKeyRef.current = pollKey;
      setSnapshotEvalBusy(true);

      try {
        for (;;) {
          if (snapshotEvalRunIdRef.current !== runId) break;
          const progress = await fetchEvaluateSearchProgress(snapshotId, jobId);
          const uiProgress = mapProgressToUi(progress);
          setSnapshotEvalProgress(uiProgress);

          if (progress.items.length > 0) {
            const updates: Record<string, number | null> = {};
            for (const row of progress.items) {
              updates[row.id] = row.llm_score ?? null;
            }
            setSnapshotEvalScores((prev) => ({ ...prev, ...updates }));
          }

          if (uiProgress.interactiveReady && !snapshotEvalInteractiveReadyRef.current) {
            snapshotEvalInteractiveReadyRef.current = true;
            await refreshCurrentResultsPage();
          }

          if (progress.status === "done") {
            await refreshCurrentResultsPage();
            break;
          }
          if (progress.status === "partial") {
            await refreshCurrentResultsPage();
            break;
          }
          if (progress.status === "error") {
            throw new ApiError(
              progress.error?.trim() || "Не удалось оценить выдачу",
              503,
              progress,
            );
          }
          if (progress.status === "cancelled") {
            break;
          }
          await new Promise((resolve) => window.setTimeout(resolve, 1200));
        }
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Не удалось оценить выдачу");
      } finally {
        setSnapshotEvalBusy(false);
        if (snapshotEvalPollKeyRef.current === pollKey) {
          snapshotEvalPollKeyRef.current = null;
        }
      }
    },
    [refreshCurrentResultsPage],
  );

  useEffect(() => {
    if (!accessToken) return;
    if (!snapshotEvalJob) return;
    if (
      snapshotEvalProgress?.status === "done" ||
      snapshotEvalProgress?.status === "partial" ||
      snapshotEvalProgress?.status === "error"
    ) {
      return;
    }
    void pollSnapshotEvaluation(snapshotEvalJob.snapshotId, snapshotEvalJob.jobId);
  }, [accessToken, snapshotEvalJob, snapshotEvalProgress?.status, pollSnapshotEvaluation]);

  useEffect(() => {
    return () => {
      snapshotEvalRunIdRef.current += 1;
      snapshotAnalyzeRunIdRef.current += 1;
    };
  }, []);

  const pollSnapshotAnalyze = useCallback(
    async (snapshotId: string, jobId: string) => {
      const pollKey = `${snapshotId}:${jobId}`;
      const runId = snapshotAnalyzeRunIdRef.current;
      if (snapshotAnalyzePollKeyRef.current === pollKey) return;
      snapshotAnalyzePollKeyRef.current = pollKey;
      setSnapshotAnalyzeBusy(true);

      try {
        for (;;) {
          if (snapshotAnalyzeRunIdRef.current !== runId) break;
          const progress = await fetchAnalyzeSearchProgress(snapshotId, jobId);
          setSnapshotAnalyzeProgress({
            status: progress.status,
            stage: progress.stage,
            total: progress.total_count,
            processed: progress.processed_count,
            analyzed: progress.analyzed_count,
          });
          if (progress.analyses && Object.keys(progress.analyses).length > 0) {
            setResults((prev) => {
              if (!prev) return prev;
              const updated = prev.items.map((item) => {
                const analysis = progress.analyses[item.id];
                if (analysis) {
                  return {
                    ...item,
                    llm_analysis: analysis,
                    llm_score: analysis.llm_score ?? item.llm_score,
                  };
                }
                return item;
              });
              return { ...prev, items: updated };
            });
          }
          if (progress.status === "done") {
            await refreshCurrentResultsPage();
            break;
          }
          if (progress.status === "error") {
            throw new ApiError(
              progress.error?.trim() || "Не удалось выполнить детальный анализ",
              503,
              progress,
            );
          }
          if (progress.status === "cancelled") {
            break;
          }
          await new Promise((resolve) => window.setTimeout(resolve, 1200));
        }
      } catch (e) {
        setError(
          e instanceof ApiError
            ? e.message
            : "Не удалось выполнить детальный анализ",
        );
      } finally {
        setSnapshotAnalyzeBusy(false);
        if (snapshotAnalyzePollKeyRef.current === pollKey) {
          snapshotAnalyzePollKeyRef.current = null;
        }
      }
    },
    [refreshCurrentResultsPage],
  );

  useEffect(() => {
    if (!accessToken) return;
    if (!snapshotAnalyzeJob) return;
    if (
      snapshotAnalyzeProgress?.status === "done" ||
      snapshotAnalyzeProgress?.status === "error"
    ) {
      return;
    }
    void pollSnapshotAnalyze(snapshotAnalyzeJob.snapshotId, snapshotAnalyzeJob.jobId);
  }, [
    accessToken,
    snapshotAnalyzeJob,
    snapshotAnalyzeProgress?.status,
    pollSnapshotAnalyze,
  ]);

  const handleEvaluateSnapshot = useCallback(async () => {
    if (!canRunEvaluate) return;
    const sid = results?.snapshot_id?.trim();
    if (!sid) return;
    snapshotEvalRunIdRef.current += 1;
    setError(null);
    setSnapshotEvalProgress({
      status: "queued",
      stage: "preparing",
      phase: "interactive",
      total: 0,
      scored: 0,
      llmScored: 0,
      fallbackScored: 0,
      coverageRatio: 0,
      llmCoverageRatio: 0,
      unresolvedCount: 0,
      llmOnlyComplete: false,
      interactiveDone: 0,
      interactiveTotal: 0,
      backgroundDone: 0,
      backgroundTotal: 0,
      interactiveFallback: 0,
      backgroundFallback: 0,
      interactiveReady: false,
    });
    snapshotEvalInteractiveReadyRef.current = false;
    try {
      const started = await startEvaluateSearchSnapshot(sid);
      setSnapshotEvalJob({
        snapshotId: sid,
        jobId: started.job_id,
      });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось оценить выдачу");
      setSnapshotEvalProgress(null);
      setSnapshotEvalJob(null);
      setSnapshotEvalBusy(false);
    }
  }, [results?.snapshot_id, canRunEvaluate]);

  const handleAnalyzeSnapshot = useCallback(async () => {
    if (!evalCompleted || evalIsActive) return;
    const sid = results?.snapshot_id?.trim();
    if (!sid) return;
    snapshotAnalyzeRunIdRef.current += 1;
    setSnapshotAnalyzeProgress({
      status: "queued",
      stage: "queued",
      total: 0,
      processed: 0,
      analyzed: 0,
    });
    setError(null);
    try {
      const started = await startAnalyzeSearchSnapshot(sid, 15);
      setSnapshotAnalyzeJob({
        snapshotId: sid,
        jobId: started.job_id,
      });
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Не удалось выполнить детальный анализ",
      );
      setSnapshotAnalyzeJob(null);
      setSnapshotAnalyzeProgress(null);
      setSnapshotAnalyzeBusy(false);
    }
  }, [results?.snapshot_id, evalCompleted, evalIsActive]);

  const handleCancelEvaluateSnapshot = useCallback(async () => {
    const job = snapshotEvalJob;
    if (!job) return;
    setError(null);
    try {
      const cancelled = await cancelEvaluateSearchSnapshot(job.snapshotId, job.jobId);
      snapshotEvalRunIdRef.current += 1;
      snapshotEvalPollKeyRef.current = null;
      setSnapshotEvalBusy(false);
      setSnapshotEvalProgress(mapProgressToUi(cancelled));
      setSnapshotEvalJob(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось остановить оценку выдачи");
    }
  }, [snapshotEvalJob]);

  const handleCancelAnalyzeSnapshot = useCallback(async () => {
    const job = snapshotAnalyzeJob;
    if (!job) return;
    setError(null);
    try {
      const cancelled = await cancelAnalyzeSearchSnapshot(job.snapshotId, job.jobId);
      snapshotAnalyzeRunIdRef.current += 1;
      snapshotAnalyzePollKeyRef.current = null;
      setSnapshotAnalyzeBusy(false);
      setSnapshotAnalyzeProgress({
        status: cancelled.status,
        stage: cancelled.stage,
        total: cancelled.total_count,
        processed: cancelled.processed_count,
        analyzed: cancelled.analyzed_count,
      });
      setSnapshotAnalyzeJob(null);
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Не удалось остановить детальный анализ",
      );
    }
  }, [snapshotAnalyzeJob]);

  const handleAnalyze = useCallback(
    async (c: Candidate) => {
      if (batchOperationActive) {
        setError("Точечная оценка доступна после завершения пакетной операции.");
        return;
      }
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
    [queryForApi, batchOperationActive],
  );

  const applyTemplate = useCallback((t: SearchTemplateRow) => {
    snapshotEvalRunIdRef.current += 1;
    snapshotAnalyzeRunIdRef.current += 1;
    const f = filtersFromApiPayload(t.filters ?? undefined);
    setFilters(f);
    setQ(t.query.trim() || "");
    setResults(null);
    setParsePreview(null);
    setError(null);
    setListFilter("");
    setListSort("server");
    setSnapshotEvalJob(null);
    setSnapshotEvalProgress(null);
    setSnapshotEvalScores({});
    setSnapshotAnalyzeJob(null);
    setSnapshotAnalyzeProgress(null);
    setSnapshotAnalyzeBusy(false);
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
      if (results != null) {
        const runId = ++listRefetchRunIdRef.current;
        void (async () => {
          setLoading(true);
          setError(null);
          try {
            const sid =
              typeof results.snapshot_id === "string" &&
              results.snapshot_id.trim()
                ? results.snapshot_id.trim()
                : null;
            const data = await fetchResultsPage(0, next, sid ?? undefined, listSort);
            if (listRefetchRunIdRef.current !== runId) return;
            setActiveTab("all");
            setResults(data);
          } catch (e) {
            if (listRefetchRunIdRef.current !== runId) return;
            if (e instanceof ApiError && (e.status === 410 || e.status === 404)) {
              setResults(null);
            }
            setError(e instanceof ApiError ? e.message : "Ошибка поиска");
          } finally {
            if (listRefetchRunIdRef.current === runId) {
              setLoading(false);
            }
          }
        })();
      }
    },
    [perPage, results, fetchResultsPage, listSort],
  );

  const handleListSortChange = useCallback(
    (next: ListSortKind) => {
      if (next === listSort) return;
      setListSort(next);
      if (!results) return;
      const runId = ++listRefetchRunIdRef.current;
      void (async () => {
        setLoading(true);
        setError(null);
        try {
          const sid =
            typeof results.snapshot_id === "string" && results.snapshot_id.trim()
              ? results.snapshot_id.trim()
              : null;
          const data = await fetchResultsPage(0, perPage, sid ?? undefined, next);
          if (listRefetchRunIdRef.current !== runId) return;
          setActiveTab("all");
          setResults(data);
        } catch (e) {
          if (listRefetchRunIdRef.current !== runId) return;
          if (e instanceof ApiError && (e.status === 410 || e.status === 404)) {
            setResults(null);
          }
          setError(e instanceof ApiError ? e.message : "Ошибка поиска");
        } finally {
          if (listRefetchRunIdRef.current === runId) {
            setLoading(false);
          }
        }
      })();
    },
    [listSort, results, fetchResultsPage, perPage],
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
  const hhFoundRaw =
    typeof results?.found_raw_hh === "number" ? results.found_raw_hh : null;
  const hhRawPool =
    typeof results?.search_metrics?.raw_pool_size === "number"
      ? results.search_metrics.raw_pool_size
      : null;
  const strictFilteredCount = results?.found ?? 0;
  const pageLocalCount = processedItems.length;
  const tabVisibleCount = filteredItems.length;
  const recallDiag = results?.search_metrics
    ? {
        primaryFound:
          typeof results.search_metrics.primary_found === "number"
            ? results.search_metrics.primary_found
            : null,
        relaxSteps:
          typeof results.search_metrics.relax_steps_used === "number"
            ? results.search_metrics.relax_steps_used
            : null,
      }
    : null;
  const effectiveSearchMode: SearchMode =
    results?.search_mode === "mass" || results?.search_mode === "precise"
      ? results.search_mode
      : searchMode;
  const hhTextOperator =
    results?.search_metrics?.text_operator === "OR" ? "OR" : "AND";
  const hhRoleIds = Array.isArray(results?.search_metrics?.professional_role_ids)
    ? (results?.search_metrics?.professional_role_ids as number[])
    : [];
  const hhSkillIds = Array.isArray(results?.search_metrics?.skill_ids)
    ? (results?.search_metrics?.skill_ids as number[])
    : [];
  const hhTextTerms = Array.isArray(results?.search_metrics?.text_terms)
    ? (results?.search_metrics?.text_terms as string[])
    : [];

  const progressValue = snapshotEvalProgress
    ? Math.min(snapshotEvalProgress.scored, snapshotEvalProgress.total)
    : 0;
  const pageButtons = (() => {
    if (!pagination) return [] as number[];
    const total = pagination.totalPages;
    if (total <= 5) return Array.from({ length: total }, (_, i) => i);
    let start = Math.max(0, pagination.pageIndex - 2);
    let end = Math.min(total - 1, start + 4);
    start = Math.max(0, end - 4);
    const pages: number[] = [];
    for (let p = start; p <= end; p += 1) pages.push(p);
    return pages;
  })();

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
              <div className="rounded-lg border bg-muted/20 p-3">
                <div className="flex items-center gap-1.5">
                  <p className="text-xs font-medium text-foreground/80">Режим поиска</p>
                  <div className="group relative inline-flex">
                    <button
                      type="button"
                      aria-label="Пояснение режимов поиска"
                      className="inline-flex h-4 w-4 items-center justify-center rounded-full text-foreground/45 transition-colors hover:text-foreground/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <CircleHelp className="h-4 w-4" />
                    </button>
                    <div className="pointer-events-none absolute left-0 top-full z-20 mt-2 hidden w-72 rounded-md border bg-background p-3 text-xs leading-5 text-foreground shadow-md group-hover:block group-focus-within:block">
                      <p>
                        <span className="font-medium">Точечный поиск</span>: ищет
                        кандидатов, у которых запрос максимально точно совпадает
                        по ключевым условиям.
                      </p>
                      <p className="mt-2">
                        <span className="font-medium">Массовый поиск</span>:
                        расширяет выдачу и находит больше кандидатов даже при
                        частичном совпадении условий.
                      </p>
                    </div>
                  </div>
                </div>
                <RadioGroup
                  value={searchMode}
                  onValueChange={(value) => setSearchMode(value as SearchMode)}
                  className="mt-2 flex flex-wrap items-center gap-4"
                >
                  <RadioGroupItemWithLabel
                    value="precise"
                    label="Точечный поиск"
                  />
                  <RadioGroupItemWithLabel
                    value="mass"
                    label="Массовый поиск"
                  />
                </RadioGroup>
              </div>
              <ActiveFiltersSummary
                filters={filters}
                areaLabels={areaLabels}
                roleLabels={roleLabels}
                parsedRegion={
                  (results?.parsed_params?.region ??
                    parsePreview?.params?.region) as string | undefined
                }
                effectiveAreaIds={
                  Array.isArray(results?.search_metrics?.area?.effective_ids)
                    ? results.search_metrics.area.effective_ids
                    : typeof results?.search_metrics?.area?.effective === "number"
                      ? [results.search_metrics.area.effective]
                      : null
                }
                effectiveAreaSource={results?.search_metrics?.area?.source}
              />
            </div>

            <div className="rounded-lg border bg-muted/20 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-display font-semibold text-foreground/80">
                  Распознанные параметры
                </h2>
                <button
                  type="button"
                  onClick={() => void runParseOnly()}
                  disabled={!queryForApi.trim() || parsing || loading}
                  className="text-sm text-primary underline disabled:pointer-events-none disabled:opacity-50"
                >
                  {parsing ? "Разбор…" : "Разобрать запрос"}
                </button>
              </div>
              <ParsedTags
                params={results?.parsed_params ?? parsePreview?.params ?? null}
                confidence={
                  results ? null : (parsePreview?.confidence ?? null)
                }
              />
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
                <div className="space-y-2">
                  <div className="flex flex-wrap gap-2">
                    {!evalCompleted && (
                      snapshotEvalBusy ? (
                        <Button
                          type="button"
                          size="sm"
                          variant="destructive"
                          disabled={loading}
                          onClick={() => void handleCancelEvaluateSnapshot()}
                        >
                          Отменить
                        </Button>
                      ) : (
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          disabled={!canRunEvaluate || loading}
                          onClick={() => void handleEvaluateSnapshot()}
                        >
                          Оценить выдачу
                        </Button>
                      )
                    )}
                    {canShowAnalyzeTop && (
                      snapshotAnalyzeBusy ? (
                        <Button
                          type="button"
                          size="sm"
                          variant="destructive"
                          disabled={loading}
                          onClick={() => void handleCancelAnalyzeSnapshot()}
                        >
                          Отменить
                        </Button>
                      ) : (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={!canRunAnalyzeTop || loading}
                          onClick={() => void handleAnalyzeSnapshot()}
                        >
                          Детальный анализ (топ-15)
                        </Button>
                      )
                    )}
                  </div>
                  {snapshotEvalProgress && evalProgressVisible && (
                    <div className={cn(
                      "space-y-2 rounded-lg border bg-muted/30 p-3 transition-opacity duration-500",
                      (
                        snapshotEvalProgress.status === "done" ||
                        snapshotEvalProgress.status === "partial" ||
                        snapshotEvalProgress.status === "error" ||
                        snapshotEvalProgress.status === "cancelled"
                      ) && "opacity-50",
                    )}>
                      <Progress
                        value={progressValue}
                        max={Math.max(snapshotEvalProgress.total, 1)}
                        label={stageLabelRu(snapshotEvalProgress.stage)}
                        showPercentage
                      />
                      <p className="text-xs text-muted-foreground">
                        {statusLabelRu(snapshotEvalProgress.status)}.{" "}
                        {evalIsActive
                          ? "Можно продолжать работать со списком и страницами — оценки подгружаются автоматически."
                          : ""}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        Проверено резюме: {snapshotEvalProgress.scored} из{" "}
                        {snapshotEvalProgress.total} (готово{" "}
                        {(snapshotEvalProgress.coverageRatio * 100).toFixed(0)}%)
                      </p>
                    </div>
                  )}
                  {snapshotAnalyzeProgress && analyzeProgressVisible && (
                    <div className={cn(
                      "space-y-2 rounded-lg border bg-muted/30 p-3 transition-opacity duration-500",
                      (
                        snapshotAnalyzeProgress.status === "done" ||
                        snapshotAnalyzeProgress.status === "error" ||
                        snapshotAnalyzeProgress.status === "cancelled"
                      ) && "opacity-50",
                    )}>
                      <Progress
                        value={Math.min(
                          snapshotAnalyzeProgress.processed,
                          snapshotAnalyzeProgress.total,
                        )}
                        max={Math.max(snapshotAnalyzeProgress.total, 1)}
                        label={analyzeStageLabelRu(snapshotAnalyzeProgress.stage)}
                        showPercentage
                      />
                      <p className="text-xs text-muted-foreground">
                        {statusLabelRu(snapshotAnalyzeProgress.status)}. Обработано:{" "}
                        {snapshotAnalyzeProgress.processed} из{" "}
                        {snapshotAnalyzeProgress.total}, с детальным выводом:{" "}
                        {snapshotAnalyzeProgress.analyzed}.
                      </p>
                    </div>
                  )}
                </div>
              )}

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
                      <Select
                        value={String(perPage)}
                        onValueChange={(val) =>
                          handlePerPageChange(Number(val) === 50 ? 50 : 20)
                        }
                      >
                        <SelectTrigger id="per-page" className="w-full min-w-0">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="20">20 резюме</SelectItem>
                          <SelectItem value="50">50 резюме</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="min-w-0 space-y-2 md:col-span-2 xl:col-span-4">
                      <Label
                        htmlFor="list-sort"
                        className="block text-xs font-medium text-muted-foreground"
                      >
                        Сортировка
                      </Label>
                      <Select
                        value={listSort}
                        onValueChange={(val) =>
                          handleListSortChange(val as ListSortKind)
                        }
                        disabled={loading}
                      >
                        <SelectTrigger id="list-sort" className="w-full min-w-0">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {LIST_SORT_OPTIONS.map((o) => (
                            <SelectItem key={o.value} value={o.value}>
                              {o.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
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
                  analyzeDisabled={batchOperationActive}
                  showEmptyGuidance={results != null && results.found === 0}
                  loading={loading}
                  estaffLatestByResumeId={estaffLatestByResumeId}
                  onEstaffExportUpdated={() => void refetchEstaffLatestMap()}
                />
              )}

              {pagination?.show && (
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
                    {pageButtons.length > 0 && pageButtons[0] > 0 && (
                      <>
                        <Button
                          type="button"
                          variant={pagination.pageIndex === 0 ? "default" : "outline"}
                          size="sm"
                          onClick={() => void goToResultsPage(0)}
                        >
                          1
                        </Button>
                        {pageButtons[0] > 1 && (
                          <span className="text-muted-foreground">...</span>
                        )}
                      </>
                    )}
                    {pageButtons.map((page) => (
                      <Button
                        key={page}
                        type="button"
                        variant={pagination.pageIndex === page ? "default" : "outline"}
                        size="sm"
                        onClick={() => void goToResultsPage(page)}
                      >
                        {page + 1}
                      </Button>
                    ))}
                    {pageButtons.length > 0 &&
                      pageButtons[pageButtons.length - 1] < pagination.totalPages - 1 && (
                        <>
                          {pageButtons[pageButtons.length - 1] < pagination.totalPages - 2 && (
                            <span className="text-muted-foreground">...</span>
                          )}
                          <Button
                            type="button"
                            variant={
                              pagination.pageIndex === pagination.totalPages - 1
                                ? "default"
                                : "outline"
                            }
                            size="sm"
                            onClick={() =>
                              void goToResultsPage(pagination.totalPages - 1)
                            }
                          >
                            {pagination.totalPages}
                          </Button>
                        </>
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
            professionalRoles={hhProfessionalRoles}
            professionalRolesLoading={hhProfessionalRolesLoading}
            professionalRolesHint={hhProfessionalRolesHint}
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
