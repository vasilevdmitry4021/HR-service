import type {
  AnalyzeSnapshotResponse,
  Candidate,
  CandidateDetail,
  EvaluateSnapshotResponse,
  FavoriteRow,
  LLMAnalysis,
  SearchHistoryListResponse,
  SearchTemplateRow,
} from "@/lib/types";

const baseUrl =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) ||
  "http://localhost:8000";

const STATUS_HINT_RU: Record<number, string> = {
  400: "Некорректный запрос",
  401: "Сессия истекла — войдите снова",
  403: "Доступ запрещён",
  404: "Не найдено",
  410: "Данные устарели — повторите действие",
  502: "Ошибка шлюза при обращении к внешнему сервису",
  409: "Конфликт данных",
  429: "Слишком много запросов. Подождите немного",
  503: "Сервис временно недоступен",
};

const SANITIZE_ERROR_MAX_LEN = 400;

/** Укорачивает и очищает текст ошибки для тостов (в т.ч. старые записи из БД). */
export function sanitizeApiErrorMessage(msg: string | null | undefined): string {
  if (msg == null || typeof msg !== "string") {
    return "Произошла ошибка. Повторите попытку позже.";
  }
  let s = msg.trim().replace(/^HTTP\s+\d{3}\s*/i, "").trim();
  if (!s) {
    return "Произошла ошибка. Повторите попытку позже.";
  }
  const lower = s.toLowerCase();
  if (lower.includes("<html")) {
    return "Сервис вернул некорректный ответ. Повторите попытку позже.";
  }
  if (s.length > SANITIZE_ERROR_MAX_LEN) {
    s = `${s.slice(0, SANITIZE_ERROR_MAX_LEN - 1)}…`;
  }
  return s;
}

function formatDetail(body: unknown): string | null {
  if (body === null || typeof body !== "object") return null;
  const d = (body as { detail?: unknown }).detail;
  if (typeof d === "string" && d.trim()) return d.trim();
  if (Array.isArray(d)) {
    const parts = d.map((item) => {
      if (typeof item === "object" && item && "msg" in item) {
        return String((item as { msg: string }).msg);
      }
      return JSON.stringify(item);
    });
    return parts.join("; ");
  }
  return null;
}

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

type Tokens = { accessToken: string; refreshToken: string };

let tokenGetter: (() => Tokens | null) | null = null;
let tokenSetter: ((t: Tokens | null) => void) | null = null;

export function bindAuthStore(
  get: () => Tokens | null,
  set: (t: Tokens | null) => void,
) {
  tokenGetter = get;
  tokenSetter = set;
}

async function refreshTokens(): Promise<Tokens | null> {
  const current = tokenGetter?.();
  if (!current?.refreshToken) return null;
  const res = await fetch(`${baseUrl}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: current.refreshToken }),
  });
  if (!res.ok) return null;
  const data = (await res.json()) as {
    access_token: string;
    refresh_token: string;
  };
  const next = {
    accessToken: data.access_token,
    refreshToken: data.refresh_token,
  };
  tokenSetter?.(next);
  return next;
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  retry = true,
): Promise<T> {
  const tokens = tokenGetter?.();
  const headers = new Headers(init.headers);
  if (tokens?.accessToken) {
    headers.set("Authorization", `Bearer ${tokens.accessToken}`);
  }
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${baseUrl}/api/v1${path}`, {
    ...init,
    headers,
  });

  if (res.status === 401 && retry && tokens?.refreshToken) {
    const refreshed = await refreshTokens();
    if (refreshed) {
      return apiFetch<T>(path, init, false);
    }
    tokenSetter?.(null);
  }

  const text = await res.text();
  let body: unknown = text;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    /* keep text */
  }

  if (!res.ok) {
    const fromBody = formatDetail(body);
    const fallback = STATUS_HINT_RU[res.status] ?? res.statusText;
    const msg = fromBody || fallback || "Ошибка запроса";
    throw new ApiError(msg, res.status, body);
  }

  return body as T;
}

export async function registerRequest(email: string, password: string) {
  return apiFetch<{ id: string; email: string; created_at: string }>(
    "/auth/register",
    {
      method: "POST",
      body: JSON.stringify({ email, password }),
    },
    false,
  );
}

export async function fetchFavorites() {
  return apiFetch<FavoriteRow[]>("/favorites");
}

export async function addFavorite(
  candidate: Pick<
    Candidate,
    | "id"
    | "hh_resume_id"
    | "title"
    | "full_name"
    | "area"
    | "skills"
    | "experience_years"
    | "age"
    | "salary"
    | "llm_analysis"
    | "llm_score"
    | "source_type"
    | "candidate_profile_id"
  >,
) {
  const llm = candidate.llm_analysis;
  const isTelegram = candidate.source_type === "telegram";
  const hhResumeId = isTelegram
    ? ""
    : (candidate.hh_resume_id || candidate.id);
  const profileId =
    isTelegram && (candidate.candidate_profile_id || candidate.id)
      ? (candidate.candidate_profile_id || candidate.id)
      : undefined;
  const scoreFromLlm = llm?.llm_score ?? null;
  const scorePrescreen = candidate.llm_score ?? null;
  return apiFetch<FavoriteRow>("/favorites", {
    method: "POST",
    body: JSON.stringify({
      hh_resume_id: hhResumeId,
      candidate_profile_id: profileId ?? null,
      title_snapshot: candidate.title ?? null,
      full_name: candidate.full_name ?? null,
      area: candidate.area ?? null,
      skills_snapshot:
        Array.isArray(candidate.skills) && candidate.skills.length > 0
          ? candidate.skills
          : null,
      experience_years: candidate.experience_years ?? null,
      age: candidate.age ?? null,
      salary_amount: candidate.salary?.amount ?? null,
      salary_currency: candidate.salary?.currency ?? null,
      llm_score: scoreFromLlm ?? scorePrescreen,
      llm_summary: llm?.summary ?? null,
      notes: "",
    }),
  });
}

export async function removeFavorite(favoriteId: string) {
  await apiFetch<unknown>(`/favorites/${favoriteId}`, { method: "DELETE" });
}

export async function patchFavoriteNotes(favoriteId: string, notes: string) {
  return apiFetch<FavoriteRow>(`/favorites/${favoriteId}/notes`, {
    method: "PATCH",
    body: JSON.stringify({ notes }),
  });
}

export async function fetchSearchHistory(skip = 0, limit = 20) {
  const q = new URLSearchParams({
    skip: String(skip),
    limit: String(limit),
  });
  return apiFetch<SearchHistoryListResponse>(`/history?${q}`);
}

export type HhAreaItem = { id: number; name: string };

/** Справочник регионов РФ (HeadHunter), кэшируется на сервере */
export async function fetchReferenceAreasRussia(): Promise<HhAreaItem[]> {
  const data = await apiFetch<{ items: HhAreaItem[] }>("/reference/areas");
  return data.items ?? [];
}

export async function fetchTemplates() {
  return apiFetch<SearchTemplateRow[]>("/templates");
}

export async function createTemplate(
  name: string,
  query: string,
  filtersPayload?: Record<string, unknown>,
) {
  const body: Record<string, unknown> = { name, query };
  if (filtersPayload && Object.keys(filtersPayload).length) {
    body.filters = filtersPayload;
  }
  return apiFetch<SearchTemplateRow>("/templates", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function updateTemplate(
  id: string,
  patch: { name?: string; query?: string; filters?: Record<string, unknown> | null },
) {
  return apiFetch<SearchTemplateRow>(`/templates/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(patch),
  });
}

export async function deleteTemplate(id: string) {
  await apiFetch<unknown>(`/templates/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export type TelegramStatusResponse = {
  feature_enabled: boolean;
  connected: boolean;
  auth_status?: string | null;
  phone_hint?: string | null;
  account_id?: string | null;
  last_sync_at?: string | null;
  awaiting_two_factor?: boolean | null;
};

export async function fetchTelegramStatus() {
  return apiFetch<TelegramStatusResponse>("/telegram/status");
}

export type TelegramSourceRow = {
  id: string;
  account_id: string;
  telegram_id: number;
  link: string;
  type: string;
  display_name: string;
  access_status: string;
  is_enabled: boolean;
  last_message_id?: number | null;
  last_check_at?: string | null;
  last_sync_at?: string | null;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
};

export async function fetchTelegramSources() {
  return apiFetch<TelegramSourceRow[]>("/telegram/sources");
}

export async function postTelegramConnect(body: {
  api_id: string;
  api_hash: string;
  phone: string;
}) {
  return apiFetch<{
    account_id: string;
    need_code: boolean;
    phone_hint?: string | null;
    message?: string | null;
  }>("/telegram/connect", { method: "POST", body: JSON.stringify(body) });
}

export async function postTelegramVerify(body: {
  account_id: string;
  code: string;
}) {
  return apiFetch<{ status: string; message?: string | null }>(
    "/telegram/verify-code",
    { method: "POST", body: JSON.stringify(body) },
  );
}

export async function postTelegramVerifyPassword(body: {
  account_id: string;
  password: string;
}) {
  return apiFetch<{ status: string; message?: string | null }>(
    "/telegram/verify-password",
    { method: "POST", body: JSON.stringify(body) },
  );
}

export async function postTelegramDisconnect() {
  return apiFetch<{ status: string }>("/telegram/disconnect", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function postTelegramSource(body: {
  link: string;
  telegram_id?: number | null;
  type?: string;
  display_name?: string;
}) {
  return apiFetch<TelegramSourceRow>("/telegram/sources", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function patchTelegramSource(
  id: string,
  patch: { is_enabled?: boolean; display_name?: string | null },
) {
  return apiFetch<TelegramSourceRow>(
    `/telegram/sources/${encodeURIComponent(id)}`,
    { method: "PATCH", body: JSON.stringify(patch) },
  );
}

export async function deleteTelegramSource(id: string) {
  await apiFetch<unknown>(`/telegram/sources/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export type TelegramSyncRunRow = {
  id: string;
  source_id: string;
  status: string;
  started_at: string;
  finished_at?: string | null;
  messages_processed: number;
  candidates_created: number;
  error_log?: unknown[] | Record<string, unknown> | null;
};

/** Проверка доступа к источнику (актуализация статуса и ошибки на сервере). */
export async function postTelegramValidateSource(sourceId: string) {
  return apiFetch<TelegramSourceRow>(
    `/telegram/sources/${encodeURIComponent(sourceId)}/validate`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

/** Постановка задачи синхронизации источника в очередь обработки. */
export async function postTelegramSyncSource(sourceId: string) {
  return apiFetch<TelegramSyncRunRow>(
    `/telegram/sources/${encodeURIComponent(sourceId)}/sync`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export async function fetchTelegramSyncRuns(limit = 50) {
  const q = new URLSearchParams({ limit: String(limit) });
  return apiFetch<TelegramSyncRunRow[]>(`/telegram/sync-runs?${q}`);
}

export async function evaluateSearchSnapshot(snapshotId: string) {
  return apiFetch<EvaluateSnapshotResponse>(
    `/search/${encodeURIComponent(snapshotId)}/evaluate`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export async function analyzeSearchSnapshot(
  snapshotId: string,
  topN: number = 15,
) {
  return apiFetch<AnalyzeSnapshotResponse>(
    `/search/${encodeURIComponent(snapshotId)}/analyze`,
    {
      method: "POST",
      body: JSON.stringify({ top_n: topN }),
    },
  );
}

export async function fetchCandidateDetail(
  resumeId: string,
  searchQuery?: string,
) {
  const q = searchQuery?.trim()
    ? `?q=${encodeURIComponent(searchQuery.trim())}`
    : "";
  return apiFetch<CandidateDetail>(
    `/candidates/${encodeURIComponent(resumeId)}${q}`,
  );
}

export async function analyzeCandidate(
  resumeId: string,
  searchQuery: string,
): Promise<LLMAnalysis> {
  const q = searchQuery.trim();
  if (!q) {
    throw new ApiError("Укажите поисковый запрос для оценки", 400, null);
  }
  const qs = `?q=${encodeURIComponent(q)}`;
  return apiFetch<LLMAnalysis>(
    `/candidates/${encodeURIComponent(resumeId)}/analyze${qs}`,
    { method: "POST" },
  );
}

/** Скачать PDF резюме (требуется FEATURE_PDF_EXPORT на бэкенде) */
export type EstaffExportStatus = "pending" | "success" | "error";

export type EstaffExportResult = {
  export_id: string;
  candidate_id: string;
  /** Устарело: для HeadHunter совпадает с candidate_id; для Telegram не заполняется */
  hh_resume_id?: string | null;
  status: EstaffExportStatus;
  estaff_candidate_id?: string | null;
  estaff_vacancy_id?: string | null;
  error_message?: string | null;
  /** Этап сбоя: получение резюме, подготовка или ответ e-staff */
  error_stage?: string | null;
  preparation_warnings?: string[] | null;
  exported_at?: string | null;
  created_at?: string | null;
};

export type LLMProvider =
  | "ollama"
  | "openai_compatible"
  | "yandex_gpt"
  | "gigachat";

export type LLMSettingsGetOut = {
  configured: boolean;
  provider?: string | null;
  model?: string | null;
  fast_model?: string | null;
  endpoint_masked?: string | null;
  endpoint?: string | null;
  folder_id?: string | null;
  client_id?: string | null;
  scope?: string | null;
};

export type LLMSettingsIn = {
  provider: LLMProvider;
  endpoint?: string | null;
  api_key?: string | null;
  model: string;
  fast_model?: string | null;
  folder_id?: string | null;
  client_id?: string | null;
  client_secret?: string | null;
  scope?: string | null;
};

export type LLMTestOut = {
  success: boolean;
  message: string;
  response_time_ms: number | null;
};

export async function fetchLLMSettingsStatus(): Promise<LLMSettingsGetOut> {
  return apiFetch<LLMSettingsGetOut>("/llm/settings");
}

export async function updateLLMSettings(
  settingsPayload: LLMSettingsIn,
): Promise<{ status: string }> {
  return apiFetch<{ status: string }>("/llm/settings", {
    method: "PUT",
    body: JSON.stringify(settingsPayload),
  });
}

export async function testLLMConnection(): Promise<LLMTestOut> {
  return apiFetch<LLMTestOut>("/llm/test", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function fetchEstaffCredentialsStatus() {
  return apiFetch<{ configured: boolean }>("/estaff/credentials");
}

export async function putEstaffCredentials(serverName: string, apiToken: string) {
  return apiFetch<{ status: string }>("/estaff/credentials", {
    method: "PUT",
    body: JSON.stringify({
      server_name: serverName,
      api_token: apiToken,
    }),
  });
}

/** Ключ localStorage для последней выбранной вакансии e-staff */
export const ESTAFF_LAST_VACANCY_STORAGE_KEY = "hr_service_estaff_last_vacancy_id";

export type EstaffVacancyItem = {
  id: string;
  title: string;
  subtitle?: string | null;
};

export async function fetchEstaffVacancies(minStart: string, maxStart: string) {
  const q = new URLSearchParams({
    min_start_date: minStart,
    max_start_date: maxStart,
  });
  return apiFetch<{ items: EstaffVacancyItem[] }>(
    `/estaff/vacancies?${q.toString()}`,
  );
}

export type EstaffExportItemPayload = {
  candidate_id?: string;
  /** Устарело: подставляется в candidate_id, если оно не задано */
  hh_resume_id?: string;
  vacancy_id: string;
  candidate?: Record<string, unknown>;
  /** Добавить HTML-вложение со ссылкой на карточку и данными ИИ */
  include_hr_llm_bundle?: boolean;
  hr_llm_summary?: string | null;
  hr_llm_score?: number | null;
  hr_search_query?: string | null;
};

/** Контекст ИИ и запроса поиска для одного идентификатора кандидата при выгрузке в e-staff */
export type EstaffHrBundleContext = {
  hr_llm_summary?: string | null;
  hr_llm_score?: number | null;
  hr_search_query?: string | null;
};

export async function postEstaffExport(items: EstaffExportItemPayload[]) {
  const payload = {
    items: items.map((it) => {
      const candidate_id = (
        it.candidate_id ||
        it.hh_resume_id ||
        ""
      ).trim();
      return {
        candidate_id,
        vacancy_id: it.vacancy_id,
        ...(it.candidate !== undefined ? { candidate: it.candidate } : {}),
        ...(it.include_hr_llm_bundle
          ? { include_hr_llm_bundle: true }
          : {}),
        ...(it.hr_llm_summary != null && it.hr_llm_summary !== ""
          ? { hr_llm_summary: it.hr_llm_summary }
          : {}),
        ...(it.hr_llm_score != null ? { hr_llm_score: it.hr_llm_score } : {}),
        ...(it.hr_search_query != null && it.hr_search_query.trim() !== ""
          ? { hr_search_query: it.hr_search_query.trim() }
          : {}),
      };
    }),
  };
  return apiFetch<{ results: EstaffExportResult[] }>("/estaff/export", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export type EstaffExportLatestResponse = {
  found: boolean;
  export_id?: string | null;
  candidate_id?: string | null;
  hh_resume_id?: string | null;
  status?: string | null;
  estaff_candidate_id?: string | null;
  error_message?: string | null;
  error_stage?: string | null;
  preparation_warnings?: string[] | null;
  exported_at?: string | null;
  created_at?: string | null;
};

export async function fetchEstaffExportLatest(candidateId: string) {
  return apiFetch<EstaffExportLatestResponse>(
    `/estaff/exports/${encodeURIComponent(candidateId)}`,
  );
}

/** Синхронно с лимитом пакетной выгрузки на бэкенде (MAX_ESTAFF_EXPORT_BATCH_RESUME_IDS). */
export const ESTAFF_EXPORT_LATEST_BATCH_MAX_IDS = 50;

export type EstaffExportLatestBatchItem = EstaffExportLatestResponse & {
  candidate_id: string;
  hh_resume_id?: string | null;
};

export async function fetchEstaffExportLatestBatch(
  candidateIds: string[],
): Promise<EstaffExportLatestBatchItem[]> {
  const seen = new Set<string>();
  const unique: string[] = [];
  for (const x of candidateIds) {
    const s = String(x).trim();
    if (!s || seen.has(s)) continue;
    seen.add(s);
    unique.push(s);
  }
  if (unique.length === 0) return [];
  const chunks: string[][] = [];
  for (let i = 0; i < unique.length; i += ESTAFF_EXPORT_LATEST_BATCH_MAX_IDS) {
    chunks.push(unique.slice(i, i + ESTAFF_EXPORT_LATEST_BATCH_MAX_IDS));
  }
  const parts = await Promise.all(
    chunks.map((ids) =>
      apiFetch<{ items: EstaffExportLatestBatchItem[] }>(
        "/estaff/exports/latest-batch",
        {
          method: "POST",
          body: JSON.stringify({ candidate_ids: ids }),
        },
      ),
    ),
  );
  return parts.flatMap((p) => p.items);
}

export async function fetchEstaffExportsHistory(page = 1, perPage = 20) {
  const q = new URLSearchParams({
    page: String(page),
    per_page: String(perPage),
  });
  return apiFetch<{
    items: {
      id: string;
      candidate_id: string;
      hh_resume_id?: string | null;
      estaff_candidate_id?: string | null;
      estaff_vacancy_id?: string | null;
      status: string;
      error_message?: string | null;
      error_stage?: string | null;
      preparation_warnings?: string[] | null;
      exported_at?: string | null;
      created_at: string;
    }[];
    total: number;
    page: number;
    per_page: number;
  }>(`/estaff/exports?${q}`);
}

export async function downloadCandidatePdfBlob(
  resumeId: string,
  retried = false,
): Promise<Blob> {
  const tokens = tokenGetter?.();
  const res = await fetch(
    `${baseUrl}/api/v1/candidates/${encodeURIComponent(resumeId)}/pdf`,
    {
      headers: tokens?.accessToken
        ? { Authorization: `Bearer ${tokens.accessToken}` }
        : {},
    },
  );
  if (res.status === 401 && !retried && tokens?.refreshToken) {
    const refreshed = await refreshTokens();
    if (refreshed) {
      return downloadCandidatePdfBlob(resumeId, true);
    }
    tokenSetter?.(null);
  }
  if (!res.ok) {
    const text = await res.text();
    let body: unknown = text;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      /* keep */
    }
    const msg = formatDetail(body) ?? STATUS_HINT_RU[res.status] ?? res.statusText;
    throw new ApiError(msg || "Ошибка загрузки PDF", res.status, body);
  }
  return res.blob();
}

export async function loginRequest(email: string, password: string) {
  const res = await fetch(`${baseUrl}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const text = await res.text();
  let body: unknown = text;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    /* keep */
  }
  if (!res.ok) {
    const msg =
      typeof body === "object" && body && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : res.statusText;
    throw new ApiError(msg || "Login failed", res.status, body);
  }
  const data = body as {
    access_token: string;
    refresh_token: string;
  };
  return {
    accessToken: data.access_token,
    refreshToken: data.refresh_token,
  };
}
