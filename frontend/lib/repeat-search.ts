/** Ключ sessionStorage для переноса запроса с страницы истории на /search */

export const HR_SEARCH_REPEAT_KEY = "hr_search_repeat";

export type RepeatSearchPayload = {
  query: string;
  filters: Record<string, unknown> | null;
};

/** Читает и удаляет payload из sessionStorage */
export function consumeRepeatSearchPayload(): RepeatSearchPayload | null {
  if (typeof window === "undefined") return null;
  const raw = sessionStorage.getItem(HR_SEARCH_REPEAT_KEY);
  if (!raw) return null;
  sessionStorage.removeItem(HR_SEARCH_REPEAT_KEY);
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
    return { query, filters };
  } catch {
    return null;
  }
}
