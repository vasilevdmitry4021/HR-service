import type { SearchResponse } from "@/lib/types";
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
    return {
      query,
      filters,
      results,
      snapshotId,
      activeTab,
      listFilter,
      listSort,
      perPage,
    };
  } catch {
    return null;
  }
}

export function clearSearchState(): void {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(HR_SEARCH_STATE_KEY);
}
