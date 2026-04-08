export type ExperienceBucket =
  | "noExperience"
  | "between1And3"
  | "between3And6"
  | "moreThan6";

/** Состояние панели фильтров (совместимо с ResumeSearchFilters на бэкенде) */
export type SearchFiltersState = {
  area: number | "";
  experience: ExperienceBucket | "";
  gender: "male" | "female" | "";
  age_from: string;
  age_to: string;
  salary_from: string;
  salary_to: string;
  currency: string;
};

export const emptySearchFilters = (): SearchFiltersState => ({
  area: "",
  experience: "",
  gender: "",
  age_from: "",
  age_to: "",
  salary_from: "",
  salary_to: "",
  currency: "RUR",
});

/** Проверяет, заданы ли какие-либо фильтры (кроме валюты по умолчанию) */
export function hasAnyFilters(s: SearchFiltersState): boolean {
  return (
    s.area !== "" ||
    s.experience !== "" ||
    s.gender !== "" ||
    s.age_from.trim() !== "" ||
    s.age_to.trim() !== "" ||
    s.salary_from.trim() !== "" ||
    s.salary_to.trim() !== ""
  );
}

const EXP_BUCKETS: ExperienceBucket[] = [
  "noExperience",
  "between1And3",
  "between3And6",
  "moreThan6",
];

/** Восстановление состояния панели из ответа API (история / шаблоны). */
export function filtersFromApiPayload(
  payload: Record<string, unknown> | null | undefined,
): SearchFiltersState {
  const base = emptySearchFilters();
  if (!payload || typeof payload !== "object") return base;
  const p = payload as Record<string, unknown>;
  if (typeof p.area === "number" && Number.isFinite(p.area)) {
    base.area = p.area;
  }
  if (typeof p.experience === "string" && EXP_BUCKETS.includes(p.experience as ExperienceBucket)) {
    base.experience = p.experience as ExperienceBucket;
  }
  if (p.gender === "male" || p.gender === "female") {
    base.gender = p.gender;
  }
  for (const key of ["age_from", "age_to", "salary_from", "salary_to"] as const) {
    const v = p[key];
    if (typeof v === "number" && Number.isFinite(v)) {
      base[key] = String(v);
    }
  }
  if (typeof p.currency === "string" && p.currency.trim()) {
    base.currency = p.currency.trim();
  }
  return base;
}

/** Тело для POST /search: только заданные поля */
export function filtersToApiPayload(
  s: SearchFiltersState,
): Record<string, unknown> | undefined {
  const out: Record<string, unknown> = {};
  if (s.area !== "") out.area = s.area;
  if (s.experience !== "") out.experience = s.experience;
  if (s.gender !== "") out.gender = s.gender;
  if (s.age_from.trim() !== "") {
    const n = parseInt(s.age_from, 10);
    if (!Number.isNaN(n)) out.age_from = n;
  }
  if (s.age_to.trim() !== "") {
    const n = parseInt(s.age_to, 10);
    if (!Number.isNaN(n)) out.age_to = n;
  }
  if (s.salary_from.trim() !== "") {
    const n = parseInt(s.salary_from, 10);
    if (!Number.isNaN(n)) out.salary_from = n;
  }
  if (s.salary_to.trim() !== "") {
    const n = parseInt(s.salary_to, 10);
    if (!Number.isNaN(n)) out.salary_to = n;
  }
  if (s.currency.trim()) out.currency = s.currency.trim();
  return Object.keys(out).length ? out : undefined;
}

export type HhAreaOption = { id: number; name: string };

/** Если API справочника недоступен */
export const FALLBACK_AREA_OPTIONS: HhAreaOption[] = [
  { id: 1, name: "Москва" },
  { id: 2, name: "Санкт-Петербург" },
  { id: 3, name: "Екатеринбург" },
  { id: 4, name: "Новосибирск" },
];

/** Сохранено для совместимости импортов */
export const AREA_OPTIONS = FALLBACK_AREA_OPTIONS;

/** Маркер строки с JSON фильтров в конце запроса (синхронизация панели ↔ текст) */
export const FILTER_SYNC_PREFIX = "\n— фильтры: ";

/** Текст запроса для API: без служебной строки фильтров */
export function queryBaseWithoutFilterLine(q: string): string {
  const idx = q.lastIndexOf(FILTER_SYNC_PREFIX);
  if (idx === -1) return q.trimEnd();
  return q.slice(0, idx).trimEnd();
}

/** Дописать/обновить строку фильтров в конце запроса */
export function mergeQueryWithFilterPayload(
  q: string,
  f: SearchFiltersState,
): string {
  const base = queryBaseWithoutFilterLine(q);
  const payload = filtersToApiPayload(f);
  if (!payload || Object.keys(payload).length === 0) {
    return base;
  }
  return `${base}${FILTER_SYNC_PREFIX}${JSON.stringify(payload)}`;
}

/** Разбор строки фильтров из полного текста (при ручном редактировании) */
export function tryParseFilterLineFromQuery(q: string): {
  base: string;
  state: SearchFiltersState | null;
} {
  const idx = q.lastIndexOf(FILTER_SYNC_PREFIX);
  if (idx === -1) {
    return { base: q.trimEnd(), state: null };
  }
  const base = q.slice(0, idx).trimEnd();
  const raw = q.slice(idx + FILTER_SYNC_PREFIX.length).trim();
  if (!raw) {
    return { base, state: emptySearchFilters() };
  }
  try {
    const obj = JSON.parse(raw) as Record<string, unknown>;
    if (typeof obj !== "object" || obj === null) {
      return { base: q.trimEnd(), state: null };
    }
    return { base, state: filtersFromApiPayload(obj) };
  } catch {
    return { base: q.trimEnd(), state: null };
  }
}

/** Подбор id региона по строке из NLP (точное имя, последний сегмент пути или единственное вхождение) */
export function findAreaIdByRegionName(
  region: string,
  areas: readonly HhAreaOption[],
): number | undefined {
  const r = region.trim().toLowerCase();
  if (!r) return undefined;
  const exact = areas.find((a) => a.name.toLowerCase() === r);
  if (exact) return exact.id;
  const byTail = areas.find((a) => {
    const parts = a.name.split(" — ");
    const last = parts[parts.length - 1]?.trim().toLowerCase();
    return last === r;
  });
  if (byTail) return byTail.id;
  const includes = areas.filter((a) => a.name.toLowerCase().includes(r));
  if (includes.length === 1) return includes[0]!.id;
  return undefined;
}

/** Поля из NLP (mock_llm), маппинг в состояние панели */
export function partialFiltersFromParsedParams(
  p: Record<string, unknown>,
  areas: readonly HhAreaOption[] = FALLBACK_AREA_OPTIONS,
): Partial<SearchFiltersState> {
  const out: Partial<SearchFiltersState> = {};
  const region = p.region;
  if (typeof region === "string" && region.trim()) {
    const id = findAreaIdByRegionName(region, areas);
    if (id !== undefined) out.area = id;
  }
  const expMin = p.experience_years_min;
  if (typeof expMin === "number" && Number.isFinite(expMin)) {
    const n = expMin;
    if (n >= 6) out.experience = "moreThan6";
    else if (n >= 3) out.experience = "between3And6";
    else if (n >= 1) out.experience = "between1And3";
    else out.experience = "noExperience";
  }
  if (p.gender === "male" || p.gender === "female") {
    out.gender = p.gender;
  }
  const ageMax = p.age_max;
  if (typeof ageMax === "number" && Number.isFinite(ageMax)) {
    out.age_to = String(ageMax);
  }
  return out;
}

/** Подмешать распознанное из текста только в пустые поля фильтров */
export function mergeNlpIntoFilters(
  prev: SearchFiltersState,
  partial: Partial<SearchFiltersState>,
): SearchFiltersState {
  const next = { ...prev };
  if (partial.area !== undefined && prev.area === "") {
    next.area = partial.area as SearchFiltersState["area"];
  }
  if (partial.experience !== undefined && prev.experience === "") {
    next.experience = partial.experience as SearchFiltersState["experience"];
  }
  if (partial.gender !== undefined && prev.gender === "") {
    next.gender = partial.gender as SearchFiltersState["gender"];
  }
  if (partial.age_to !== undefined && prev.age_to === "") {
    next.age_to = partial.age_to;
  }
  if (partial.age_from !== undefined && prev.age_from === "") {
    next.age_from = partial.age_from;
  }
  if (partial.salary_from !== undefined && prev.salary_from === "") {
    next.salary_from = partial.salary_from;
  }
  if (partial.salary_to !== undefined && prev.salary_to === "") {
    next.salary_to = partial.salary_to;
  }
  return next;
}

const EXPERIENCE_LABELS: Record<ExperienceBucket, string> = {
  noExperience: "Без опыта",
  between1And3: "1–3 года",
  between3And6: "3–6 лет",
  moreThan6: "Более 6 лет",
};

const GENDER_LABELS: Record<"male" | "female", string> = {
  male: "Мужской",
  female: "Женский",
};

/** Человекочитаемые метки активных фильтров для отображения под полем поиска */
export function filtersToReadableSummary(
  f: SearchFiltersState,
  areaLabels?: Map<number, string>,
): string[] {
  const out: string[] = [];
  if (f.area !== "") {
    const fromMap = areaLabels?.get(f.area);
    const fromFallback = FALLBACK_AREA_OPTIONS.find((a) => a.id === f.area)?.name;
    const areaLabel = fromMap ?? fromFallback;
    if (areaLabel) out.push(areaLabel);
    else out.push(`Регион №${f.area}`);
  }
  if (f.experience !== "") {
    out.push(EXPERIENCE_LABELS[f.experience]);
  }
  if (f.gender !== "") {
    out.push(GENDER_LABELS[f.gender]);
  }
  const hasAgeFrom = f.age_from.trim() !== "";
  const hasAgeTo = f.age_to.trim() !== "";
  if (hasAgeFrom || hasAgeTo) {
    if (hasAgeFrom && hasAgeTo) {
      out.push(`Возраст: ${f.age_from}–${f.age_to}`);
    } else if (hasAgeFrom) {
      out.push(`Возраст: от ${f.age_from}`);
    } else {
      out.push(`Возраст: до ${f.age_to}`);
    }
  }
  const hasSalFrom = f.salary_from.trim() !== "";
  const hasSalTo = f.salary_to.trim() !== "";
  if (hasSalFrom || hasSalTo) {
    const cur = f.currency.trim() && f.currency !== "RUR" ? ` ${f.currency}` : "";
    if (hasSalFrom && hasSalTo) {
      out.push(`Зарплата: ${f.salary_from}–${f.salary_to}${cur}`);
    } else if (hasSalFrom) {
      out.push(`Зарплата: от ${f.salary_from}${cur}`);
    } else {
      out.push(`Зарплата: до ${f.salary_to}${cur}`);
    }
  }
  return out;
}
