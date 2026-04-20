import type { SearchMode, SearchResponse } from "@/lib/types";
import type { ListSortKind } from "@/lib/search-results-list";

export const HR_SEARCH_STATE_KEY = "hr_search_state";

export type ResultTab = "all" | "relevant" | "strong" | "good";

const LIST_SORT_VALUES: readonly ListSortKind[] = [
  "server",
  "llm_desc",
  "llm_score_desc",
  "experience_desc",
  "experience_asc",
];

function isListSortKind(v: unknown): v is ListSortKind {
  return typeof v === "string" && LIST_SORT_VALUES.includes(v as ListSortKind);
}

/** Сохранённые сессии со старым значением сортировки */
function migrateListSort(v: unknown): ListSortKind | undefined {
  if (v === "relevance_desc") return "llm_score_desc";
  return isListSortKind(v) ? v : undefined;
}

const RESULT_TABS: readonly ResultTab[] = [
  "all",
  "relevant",
  "strong",
  "good",
];

function isResultTab(v: unknown): v is ResultTab {
  return typeof v === "string" && RESULT_TABS.includes(v as ResultTab);
}

function parseStoredResults(v: unknown): SearchResponse | null {
  if (v === null || v === undefined) return null;
  if (typeof v !== "object") return null;
  const o = v as Record<string, unknown>;
  if (!Array.isArray(o.items)) return null;
  return v as SearchResponse;
}

export type SearchStatePayload = {
  query: string;
  filters: Record<string, unknown> | null;
  results: SearchResponse | null;
  /** Идентификатор снимка выдачи для пагинации (дублирует results.snapshot_id при наличии). */
  snapshotId?: string | null;
  activeTab: ResultTab;
  listFilter?: string;
  listSort?: ListSortKind;
  perPage?: number;
  searchMode?: SearchMode;
  snapshotEvalJob?: {
    snapshotId: string;
    jobId: string;
  } | null;
  snapshotEvalProgress?: {
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
  } | null;
  snapshotAnalyzeJob?: {
    snapshotId: string;
    jobId: string;
  } | null;
  snapshotAnalyzeProgress?: {
    status: string;
    stage: string;
    total: number;
    processed: number;
    analyzed: number;
  } | null;
};

export function saveSearchState(state: SearchStatePayload): void {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.setItem(HR_SEARCH_STATE_KEY, JSON.stringify(state));
  } catch {
    /* квота или приватный режим */
  }
}

export function readSearchState(): SearchStatePayload | null {
  if (typeof window === "undefined") return null;
  const raw = sessionStorage.getItem(HR_SEARCH_STATE_KEY);
  if (!raw) return null;
  try {
    const p = JSON.parse(raw) as unknown;
    if (!p || typeof p !== "object") return null;
    const o = p as Record<string, unknown>;
    const query = typeof o.query === "string" ? o.query : "";
    const filters =
      o.filters === null || o.filters === undefined
        ? null
        : typeof o.filters === "object" && !Array.isArray(o.filters)
          ? (o.filters as Record<string, unknown>)
          : null;
    const results = parseStoredResults(o.results);
    const snapshotIdFromResults =
      results &&
      typeof results.snapshot_id === "string" &&
      results.snapshot_id.trim()
        ? results.snapshot_id.trim()
        : null;
    const snapshotIdRaw = o.snapshotId;
    const snapshotId =
      typeof snapshotIdRaw === "string" && snapshotIdRaw.trim()
        ? snapshotIdRaw.trim()
        : snapshotIdFromResults;
    const activeTab = isResultTab(o.activeTab) ? o.activeTab : "all";
    const listFilter = typeof o.listFilter === "string" ? o.listFilter : "";
    const listSort = migrateListSort(o.listSort);
    const perPage =
      typeof o.perPage === "number" &&
      Number.isFinite(o.perPage) &&
      (o.perPage === 20 || o.perPage === 50)
        ? o.perPage
        : undefined;
    const searchMode =
      o.searchMode === "mass" || o.searchMode === "precise"
        ? o.searchMode
        : undefined;
    const snapshotEvalJobRaw = o.snapshotEvalJob;
    const snapshotEvalJob =
      snapshotEvalJobRaw &&
      typeof snapshotEvalJobRaw === "object" &&
      typeof (snapshotEvalJobRaw as { snapshotId?: unknown }).snapshotId ===
        "string" &&
      typeof (snapshotEvalJobRaw as { jobId?: unknown }).jobId === "string"
        ? {
            snapshotId: (
              snapshotEvalJobRaw as { snapshotId: string }
            ).snapshotId.trim(),
            jobId: (snapshotEvalJobRaw as { jobId: string }).jobId.trim(),
          }
        : null;
    const progressRaw = o.snapshotEvalProgress;
    const snapshotEvalProgress =
      progressRaw && typeof progressRaw === "object"
        ? ({
            status:
              typeof (progressRaw as { status?: unknown }).status === "string"
                ? String((progressRaw as { status: string }).status)
                : "running",
            stage:
              typeof (progressRaw as { stage?: unknown }).stage === "string"
                ? String((progressRaw as { stage: string }).stage)
                : "",
            phase:
              typeof (progressRaw as { phase?: unknown }).phase === "string"
                ? String((progressRaw as { phase: string }).phase)
                : "interactive",
            total: Number((progressRaw as { total?: unknown }).total ?? 0) || 0,
            scored: Number((progressRaw as { scored?: unknown }).scored ?? 0) || 0,
            llmScored:
              Number((progressRaw as { llmScored?: unknown }).llmScored ?? 0) || 0,
            fallbackScored:
              Number(
                (progressRaw as { fallbackScored?: unknown }).fallbackScored ?? 0,
              ) || 0,
            coverageRatio:
              Number(
                (progressRaw as { coverageRatio?: unknown }).coverageRatio ?? 0,
              ) || 0,
            llmCoverageRatio:
              Number(
                (progressRaw as { llmCoverageRatio?: unknown }).llmCoverageRatio ??
                  (progressRaw as { coverageRatio?: unknown }).coverageRatio ??
                  0,
              ) || 0,
            unresolvedCount:
              Number(
                (progressRaw as { unresolvedCount?: unknown }).unresolvedCount ?? 0,
              ) || 0,
            llmOnlyComplete: Boolean(
              (progressRaw as { llmOnlyComplete?: unknown }).llmOnlyComplete,
            ),
            interactiveDone:
              Number(
                (progressRaw as { interactiveDone?: unknown }).interactiveDone ?? 0,
              ) || 0,
            interactiveTotal:
              Number(
                (progressRaw as { interactiveTotal?: unknown }).interactiveTotal ?? 0,
              ) || 0,
            backgroundDone:
              Number(
                (progressRaw as { backgroundDone?: unknown }).backgroundDone ?? 0,
              ) || 0,
            backgroundTotal:
              Number(
                (progressRaw as { backgroundTotal?: unknown }).backgroundTotal ?? 0,
              ) || 0,
            interactiveFallback:
              Number(
                (progressRaw as { interactiveFallback?: unknown })
                  .interactiveFallback ?? 0,
              ) || 0,
            backgroundFallback:
              Number(
                (progressRaw as { backgroundFallback?: unknown })
                  .backgroundFallback ?? 0,
              ) || 0,
            interactiveReady:
              Boolean(
                (progressRaw as { interactiveReady?: unknown }).interactiveReady,
              ),
          } satisfies NonNullable<SearchStatePayload["snapshotEvalProgress"]>)
        : null;
    const snapshotAnalyzeJobRaw = o.snapshotAnalyzeJob;
    const snapshotAnalyzeJob =
      snapshotAnalyzeJobRaw &&
      typeof snapshotAnalyzeJobRaw === "object" &&
      typeof (snapshotAnalyzeJobRaw as { snapshotId?: unknown }).snapshotId ===
        "string" &&
      typeof (snapshotAnalyzeJobRaw as { jobId?: unknown }).jobId === "string"
        ? {
            snapshotId: (
              snapshotAnalyzeJobRaw as { snapshotId: string }
            ).snapshotId.trim(),
            jobId: (snapshotAnalyzeJobRaw as { jobId: string }).jobId.trim(),
          }
        : null;
    const analyzeProgressRaw = o.snapshotAnalyzeProgress;
    const snapshotAnalyzeProgress =
      analyzeProgressRaw && typeof analyzeProgressRaw === "object"
        ? ({
            status:
              typeof (analyzeProgressRaw as { status?: unknown }).status ===
              "string"
                ? String((analyzeProgressRaw as { status: string }).status)
                : "running",
            stage:
              typeof (analyzeProgressRaw as { stage?: unknown }).stage ===
              "string"
                ? String((analyzeProgressRaw as { stage: string }).stage)
                : "",
            total:
              Number((analyzeProgressRaw as { total?: unknown }).total ?? 0) ||
              0,
            processed:
              Number(
                (analyzeProgressRaw as { processed?: unknown }).processed ?? 0,
              ) || 0,
            analyzed:
              Number(
                (analyzeProgressRaw as { analyzed?: unknown }).analyzed ?? 0,
              ) || 0,
          } satisfies NonNullable<SearchStatePayload["snapshotAnalyzeProgress"]>)
        : null;
    return {
      query,
      filters,
      results,
      snapshotId,
      activeTab,
      listFilter,
      listSort,
      perPage,
      searchMode,
      snapshotEvalJob:
        snapshotEvalJob &&
        snapshotEvalJob.snapshotId.length > 0 &&
        snapshotEvalJob.jobId.length > 0
          ? snapshotEvalJob
          : null,
      snapshotEvalProgress,
      snapshotAnalyzeJob:
        snapshotAnalyzeJob &&
        snapshotAnalyzeJob.snapshotId.length > 0 &&
        snapshotAnalyzeJob.jobId.length > 0
          ? snapshotAnalyzeJob
          : null,
      snapshotAnalyzeProgress,
    };
  } catch {
    return null;
  }
}

export function clearSearchState(): void {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(HR_SEARCH_STATE_KEY);
}
