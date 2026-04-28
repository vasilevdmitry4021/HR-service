"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { AppNav } from "@/components/AppNav";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  ApiError,
  fetchRequestLog,
  fetchRequestLogErrors,
  fetchRequestLogStats,
  sanitizeApiErrorMessage,
  type RequestLogFilters,
} from "@/lib/api";
import type {
  RequestLogByDay,
  RequestLogEntry,
  RequestLogErrorGroup,
  RequestLogIntegrationSummary,
  RequestLogStats,
} from "@/lib/types";
import { useAuthStore } from "@/stores/auth-store";

const PAGE_SIZE = 50;

const ROUTE_TAG_LABELS: Record<string, string> = {
  search: "Поиск",
  parse: "Разбор запроса",
  evaluate: "Оценка",
  analyze: "Анализ",
  estaff_export: "Выгрузка e-staff",
  estaff_vacancies: "Вакансии e-staff",
  llm_settings: "Настройки LLM",
  auth: "Авторизация",
  other: "Прочее",
};

const ERROR_TYPE_LABELS: Record<string, string> = {
  hh_permission: "Доступ HH",
  hh_rate_limit: "Лимит HH",
  llm_timeout: "Таймаут LLM",
  estaff_connection: "Подключение e-staff",
  internal: "Внутренняя ошибка",
};

function fmtDt(iso: string | null | undefined) {
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

function fmtDur(ms: number | null | undefined) {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} мс`;
  return `${(ms / 1000).toFixed(1)} с`;
}

function statusClass(code: number) {
  if (code < 300) return "text-emerald-600 dark:text-emerald-400";
  if (code < 400) return "text-blue-500";
  if (code < 500) return "text-amber-600";
  return "text-destructive";
}

function isoDateOnly(d: Date) {
  return d.toISOString().slice(0, 10);
}

function defaultDateFrom() {
  const d = new Date();
  d.setDate(d.getDate() - 7);
  return isoDateOnly(d);
}

function defaultDateTo() {
  return isoDateOnly(new Date());
}

// ─── Summary cards ───────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {sub ? <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p> : null}
    </div>
  );
}

// ─── Detail panel ────────────────────────────────────────────────────────────

function EntryDetail({ entry }: { entry: RequestLogEntry }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    void navigator.clipboard.writeText(JSON.stringify(entry, null, 2)).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="mt-3 rounded-lg border border-border bg-muted/30 p-4 text-sm space-y-3">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-muted-foreground">
          request_id: <span className="font-mono text-foreground">{entry.request_id}</span>
        </span>
        <Button type="button" variant="outline" size="sm" onClick={handleCopy}>
          {copied ? "Скопировано" : "Копировать JSON"}
        </Button>
      </div>

      {entry.query_id ? (
        <p className="text-muted-foreground">
          query_id: <span className="font-mono text-foreground">{entry.query_id}</span>
        </p>
      ) : null}

      {entry.request_body_summary ? (
        <div>
          <p className="font-medium mb-1">Параметры запроса</p>
          <pre className="overflow-x-auto rounded bg-background p-2 text-xs text-foreground whitespace-pre-wrap">
            {JSON.stringify(entry.request_body_summary, null, 2)}
          </pre>
        </div>
      ) : null}

      {entry.response_summary ? (
        <div>
          <p className="font-medium mb-1">Итог ответа</p>
          <pre className="overflow-x-auto rounded bg-background p-2 text-xs text-foreground whitespace-pre-wrap">
            {JSON.stringify(entry.response_summary, null, 2)}
          </pre>
        </div>
      ) : null}

      {entry.search_metrics ? (
        <div>
          <p className="font-medium mb-1">Метрики поиска</p>
          <pre className="overflow-x-auto rounded bg-background p-2 text-xs text-foreground whitespace-pre-wrap">
            {JSON.stringify(entry.search_metrics, null, 2)}
          </pre>
        </div>
      ) : null}

      {entry.integration_calls && entry.integration_calls.length > 0 ? (
        <div>
          <p className="font-medium mb-1">Внешние вызовы</p>
          <ul className="space-y-1">
            {entry.integration_calls.map((call, i) => (
              <li key={i} className="flex flex-wrap gap-2 rounded bg-background px-3 py-1.5 text-xs">
                <span className="font-medium">{call.system}</span>
                <span className="text-muted-foreground">{call.operation}</span>
                <span className={call.status_code && call.status_code >= 400 ? "text-destructive" : "text-emerald-600 dark:text-emerald-400"}>
                  {call.status_code ?? "—"}
                </span>
                <span className="text-muted-foreground">{fmtDur(call.duration_ms)}</span>
                {call.cached ? <span className="text-blue-500">кэш</span> : null}
                {call.error ? <span className="text-destructive">{call.error}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {entry.error_message ? (
        <div>
          <p className="font-medium mb-1 text-destructive">Ошибка</p>
          <p className="text-destructive">{entry.error_message}</p>
          {entry.error_type ? (
            <p className="mt-0.5 text-xs text-muted-foreground">
              Тип: {ERROR_TYPE_LABELS[entry.error_type] ?? entry.error_type}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

// ─── Journal tab ─────────────────────────────────────────────────────────────

function JournalTab() {
  const [items, setItems] = useState<RequestLogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [skip, setSkip] = useState(0);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const [dateFrom, setDateFrom] = useState(defaultDateFrom);
  const [dateTo, setDateTo] = useState(defaultDateTo);
  const [routeTag, setRouteTag] = useState("");
  const [search, setSearch] = useState("");
  const [onlyErrors, setOnlyErrors] = useState(false);

  const load = useCallback(
    async (overrideSkip?: number) => {
      setLoading(true);
      setError(null);
      const s = overrideSkip ?? skip;
      const filters: RequestLogFilters = {
        skip: s,
        limit: PAGE_SIZE,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        route_tag: routeTag || undefined,
        search: search.trim() || undefined,
        status_min: onlyErrors ? 400 : undefined,
      };
      try {
        const data = await fetchRequestLog(filters);
        setItems(data.items);
        setTotal(data.total);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Не удалось загрузить журнал");
      } finally {
        setLoading(false);
      }
    },
    [skip, dateFrom, dateTo, routeTag, search, onlyErrors],
  );

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function applyFilters() {
    setSkip(0);
    void load(0);
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.floor(skip / PAGE_SIZE) + 1;

  function goPage(p: number) {
    const s = (p - 1) * PAGE_SIZE;
    setSkip(s);
    void load(s);
  }

  const successCount = items.filter((i) => i.status_code < 400).length;
  const errCount = items.filter((i) => i.status_code >= 400).length;
  const avgDur =
    items.length > 0
      ? Math.round(items.reduce((a, b) => a + b.duration_ms, 0) / items.length)
      : 0;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Всего в выборке" value={total} />
        <StatCard label="Успешных" value={successCount} />
        <StatCard label="С ошибкой" value={errCount} />
        <StatCard label="Среднее время" value={fmtDur(avgDur)} />
      </div>

      <div className="flex flex-wrap gap-3 rounded-lg border border-border bg-card p-4">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">С</label>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">По</label>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">Тип операции</label>
          <select
            value={routeTag}
            onChange={(e) => setRouteTag(e.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          >
            <option value="">Все</option>
            {Object.entries(ROUTE_TAG_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1 flex-1 min-w-[140px]">
          <label className="text-xs text-muted-foreground">Поиск (запрос, ID)</label>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Текст поиска…"
            className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
            onKeyDown={(e) => {
              if (e.key === "Enter") applyFilters();
            }}
          />
        </div>
        <div className="flex items-end gap-2">
          <label className="flex items-center gap-1.5 text-sm cursor-pointer select-none">
            <input
              type="checkbox"
              checked={onlyErrors}
              onChange={(e) => setOnlyErrors(e.target.checked)}
              className="rounded"
            />
            Только ошибки
          </label>
        </div>
        <div className="flex items-end">
          <Button type="button" size="sm" onClick={applyFilters} disabled={loading}>
            Применить
          </Button>
        </div>
      </div>

      {error ? (
        <p className="text-sm text-destructive">{sanitizeApiErrorMessage(error)}</p>
      ) : null}

      {loading ? (
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">
          Записей не найдено
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-muted/50">
              <tr>
                <th className="px-3 py-2.5 text-left text-xs font-medium text-muted-foreground">Время</th>
                <th className="px-3 py-2.5 text-left text-xs font-medium text-muted-foreground">Пользователь</th>
                <th className="px-3 py-2.5 text-left text-xs font-medium text-muted-foreground">Операция</th>
                <th className="px-3 py-2.5 text-left text-xs font-medium text-muted-foreground">Запрос</th>
                <th className="px-3 py-2.5 text-left text-xs font-medium text-muted-foreground">Статус</th>
                <th className="px-3 py-2.5 text-left text-xs font-medium text-muted-foreground">Время</th>
                <th className="px-3 py-2.5 text-left text-xs font-medium text-muted-foreground">Найдено</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {items.map((row) => {
                const isExpanded = expandedId === row.request_id;
                const queryText =
                  typeof row.request_body_summary?.query === "string"
                    ? row.request_body_summary.query
                    : null;
                const found =
                  typeof row.response_summary?.found === "number"
                    ? row.response_summary.found
                    : null;
                return (
                  <>
                    <tr
                      key={row.request_id}
                      className="cursor-pointer hover:bg-muted/30 transition-colors"
                      onClick={() =>
                        setExpandedId(isExpanded ? null : row.request_id)
                      }
                    >
                      <td className="px-3 py-2.5 text-xs whitespace-nowrap text-muted-foreground">
                        {fmtDt(row.created_at)}
                      </td>
                      <td className="px-3 py-2.5 max-w-[150px] truncate text-xs">
                        {row.user_email ?? <span className="text-muted-foreground">—</span>}
                      </td>
                      <td className="px-3 py-2.5 text-xs">
                        {ROUTE_TAG_LABELS[row.route_tag] ?? row.route_tag}
                      </td>
                      <td className="px-3 py-2.5 max-w-[200px] truncate text-xs text-muted-foreground">
                        {queryText ?? row.route}
                      </td>
                      <td className={`px-3 py-2.5 text-xs font-medium ${statusClass(row.status_code)}`}>
                        {row.status_code}
                      </td>
                      <td className="px-3 py-2.5 text-xs tabular-nums text-muted-foreground">
                        {fmtDur(row.duration_ms)}
                      </td>
                      <td className="px-3 py-2.5 text-xs tabular-nums text-muted-foreground">
                        {found != null ? found : "—"}
                      </td>
                    </tr>
                    {isExpanded ? (
                      <tr key={`${row.request_id}-detail`}>
                        <td colSpan={7} className="px-3 pb-3">
                          <EntryDetail entry={row} />
                        </td>
                      </tr>
                    ) : null}
                  </>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {totalPages > 1 ? (
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            Страница {currentPage} из {totalPages} (всего {total})
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={currentPage <= 1 || loading}
              onClick={() => goPage(currentPage - 1)}
            >
              Назад
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={currentPage >= totalPages || loading}
              onClick={() => goPage(currentPage + 1)}
            >
              Вперёд
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ─── Errors tab ───────────────────────────────────────────────────────────────

function ErrorsTab() {
  const [items, setItems] = useState<RequestLogErrorGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [dateFrom, setDateFrom] = useState(defaultDateFrom);
  const [dateTo, setDateTo] = useState(defaultDateTo);
  const [routeTag, setRouteTag] = useState("");
  const [errorType, setErrorType] = useState("");

  const load = useCallback(
    async (params?: { dateFrom: string; dateTo: string; routeTag: string; errorType: string }) => {
      setLoading(true);
      setError(null);
      const p = params ?? { dateFrom, dateTo, routeTag, errorType };
      try {
        const data = await fetchRequestLogErrors({
          date_from: p.dateFrom || undefined,
          date_to: p.dateTo || undefined,
          route_tag: p.routeTag || undefined,
          error_type: p.errorType || undefined,
        });
        setItems(data.items);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Не удалось загрузить ошибки");
      } finally {
        setLoading(false);
      }
    },
    [dateFrom, dateTo, routeTag, errorType],
  );

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function applyFilters() {
    void load({ dateFrom, dateTo, routeTag, errorType });
  }

  function severityVariant(count: number): "destructive" | "warning" {
    return count >= 10 ? "destructive" : "warning";
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3 rounded-lg border border-border bg-card p-4">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">С</label>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">По</label>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">Тип операции</label>
          <select
            value={routeTag}
            onChange={(e) => setRouteTag(e.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          >
            <option value="">Все</option>
            {Object.entries(ROUTE_TAG_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">Тип ошибки</label>
          <select
            value={errorType}
            onChange={(e) => setErrorType(e.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          >
            <option value="">Все</option>
            {Object.entries(ERROR_TYPE_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-end">
          <Button type="button" size="sm" onClick={applyFilters} disabled={loading}>
            Применить
          </Button>
        </div>
      </div>

      {error ? (
        <p className="text-sm text-destructive">{sanitizeApiErrorMessage(error)}</p>
      ) : null}

      {loading ? (
        <div className="space-y-2">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">
          Ошибок в выбранном периоде не найдено
        </p>
      ) : (
        <ul className="space-y-3">
          {items.map((group, i) => (
            <li key={i} className="rounded-lg border border-border bg-card p-4 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={severityVariant(group.count)} dot>
                  {group.count}
                </Badge>
                <span className="font-medium text-sm">
                  {ERROR_TYPE_LABELS[group.error_type] ?? group.error_type}
                </span>
                <span className="text-xs text-muted-foreground">
                  последнее: {fmtDt(group.last_seen)}
                </span>
              </div>
              {group.error_message ? (
                <p className="text-sm text-muted-foreground line-clamp-2">
                  {group.error_message}
                </p>
              ) : null}
              <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                <span>
                  Маршруты:{" "}
                  {group.route_tags
                    .map((t) => ROUTE_TAG_LABELS[t] ?? t)
                    .join(", ") || "—"}
                </span>
                <span>·</span>
                <span>Пользователей: {group.affected_users_count}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ─── Simple canvas charts ─────────────────────────────────────────────────────

function BarChart({
  data,
  labelKey,
  valueKey,
  color = "#6366f1",
  title,
}: {
  data: Record<string, unknown>[];
  labelKey: string;
  valueKey: string;
  color?: string;
  title?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || data.length === 0) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const W = canvas.offsetWidth;
    const H = canvas.offsetHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    ctx.scale(dpr, dpr);

    ctx.clearRect(0, 0, W, H);

    const pad = { top: 20, right: 12, bottom: 48, left: 48 };
    const values = data.map((d) => Number(d[valueKey]) || 0);
    const maxVal = Math.max(...values, 1);
    const barW = (W - pad.left - pad.right) / data.length;

    ctx.fillStyle = getComputedStyle(canvas).getPropertyValue("color") || "#888";
    ctx.font = "11px system-ui, sans-serif";

    values.forEach((v, i) => {
      const x = pad.left + i * barW;
      const barH = ((v / maxVal) * (H - pad.top - pad.bottom)) || 0;
      const y = H - pad.bottom - barH;

      ctx.fillStyle = color;
      ctx.fillRect(x + barW * 0.1, y, barW * 0.8, barH);

      const label = String(data[i][labelKey] ?? "").slice(-5);
      ctx.fillStyle = "#888";
      ctx.textAlign = "center";
      ctx.fillText(label, x + barW / 2, H - pad.bottom + 14);
    });

    ctx.fillStyle = "#888";
    ctx.textAlign = "right";
    [0, 0.5, 1].forEach((t) => {
      const y = H - pad.bottom - t * (H - pad.top - pad.bottom);
      ctx.fillText(String(Math.round(maxVal * t)), pad.left - 4, y + 4);
      ctx.strokeStyle = "#e5e7eb";
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(W - pad.right, y);
      ctx.stroke();
    });
  }, [data, labelKey, valueKey, color]);

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      {title ? <p className="mb-2 text-sm font-medium">{title}</p> : null}
      <canvas ref={canvasRef} className="h-48 w-full" />
    </div>
  );
}

// ─── Analytics tab ────────────────────────────────────────────────────────────

function AnalyticsTab() {
  const [stats, setStats] = useState<RequestLogStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [dateFrom, setDateFrom] = useState(defaultDateFrom);
  const [dateTo, setDateTo] = useState(defaultDateTo);

  const load = useCallback(async (df?: string, dt?: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchRequestLogStats(df ?? dateFrom, dt ?? dateTo);
      setStats(data);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось загрузить аналитику");
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo]);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function applyFilters() {
    void load(dateFrom, dateTo);
  }

  const byDayForBar: RequestLogByDay[] = stats?.by_day ?? [];
  const integrationData: RequestLogIntegrationSummary[] = stats?.integration_summary ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-3 rounded-lg border border-border bg-card p-4">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">С</label>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">По</label>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          />
        </div>
        <div className="flex items-end">
          <Button type="button" size="sm" onClick={applyFilters} disabled={loading}>
            Применить
          </Button>
        </div>
      </div>

      {error ? (
        <p className="text-sm text-destructive">{sanitizeApiErrorMessage(error)}</p>
      ) : null}

      {loading ? (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[...Array(4)].map((_, i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
          <Skeleton className="h-56 w-full" />
          <Skeleton className="h-56 w-full" />
        </div>
      ) : stats == null ? null : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard label="Всего запросов" value={stats.total_requests} />
            <StatCard label="Успешных" value={stats.success_count} />
            <StatCard label="С ошибкой" value={stats.error_count} />
            <StatCard
              label="Среднее время"
              value={fmtDur(stats.avg_duration_ms)}
              sub={`P95: ${fmtDur(stats.p95_duration_ms)}`}
            />
          </div>

          {byDayForBar.length > 0 ? (
            <div className="grid gap-4 lg:grid-cols-2">
              <BarChart
                data={byDayForBar}
                labelKey="date"
                valueKey="count"
                color="#6366f1"
                title="Запросы по дням"
              />
              <BarChart
                data={byDayForBar}
                labelKey="date"
                valueKey="avg_duration_ms"
                color="#f59e0b"
                title="Среднее время ответа по дням (мс)"
              />
            </div>
          ) : null}

          {integrationData.length > 0 ? (
            <BarChart
              data={integrationData}
              labelKey="system"
              valueKey="error_rate"
              color="#ef4444"
              title="Доля ошибок по внешним системам"
            />
          ) : null}

          {stats.by_route_tag.length > 0 ? (
            <div className="rounded-lg border border-border bg-card">
              <div className="border-b border-border px-4 py-3">
                <p className="font-medium text-sm">Распределение по типам операций</p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b border-border bg-muted/50">
                    <tr>
                      <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">Операция</th>
                      <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">Запросов</th>
                      <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">Ошибок</th>
                      <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">Среднее время</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {stats.by_route_tag.map((row) => (
                      <tr key={row.route_tag}>
                        <td className="px-4 py-2.5 text-sm">
                          {ROUTE_TAG_LABELS[row.route_tag] ?? row.route_tag}
                        </td>
                        <td className="px-4 py-2.5 text-right tabular-nums">{row.count}</td>
                        <td className={`px-4 py-2.5 text-right tabular-nums ${row.error_count > 0 ? "text-destructive" : "text-muted-foreground"}`}>
                          {row.error_count}
                        </td>
                        <td className="px-4 py-2.5 text-right tabular-nums text-muted-foreground">
                          {fmtDur(row.avg_duration_ms)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}

          {stats.top_errors.length > 0 ? (
            <div className="rounded-lg border border-border bg-card">
              <div className="border-b border-border px-4 py-3">
                <p className="font-medium text-sm">Самые частые ошибки</p>
              </div>
              <ul className="divide-y divide-border">
                {stats.top_errors.map((e, i) => (
                  <li key={i} className="flex items-baseline justify-between gap-3 px-4 py-3 text-sm">
                    <span className="min-w-0 truncate text-muted-foreground">
                      <span className="font-medium text-foreground">
                        {ERROR_TYPE_LABELS[e.error_type] ?? e.error_type}
                      </span>
                      {e.error_message ? ` — ${e.error_message}` : ""}
                    </span>
                    <span className="shrink-0 tabular-nums text-destructive font-medium">
                      {e.count}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

type TabId = "journal" | "errors" | "analytics";

export default function RequestLogPage() {
  const router = useRouter();
  const accessToken = useAuthStore((s) => s.accessToken);
  const isAdmin = useAuthStore((s) => s.isAdmin);
  const hasHydrated = useAuthStore((s) => s._hasHydrated);

  const [activeTab, setActiveTab] = useState<TabId>("journal");

  useEffect(() => {
    if (!hasHydrated) return;
    if (!accessToken) {
      router.replace("/login");
      return;
    }
    if (isAdmin === false) {
      router.replace("/search");
    }
  }, [hasHydrated, accessToken, isAdmin, router]);

  if (!hasHydrated) {
    return (
      <main className="flex min-h-screen items-center justify-center p-4">
        <p className="text-muted-foreground">Загрузка…</p>
      </main>
    );
  }
  if (!accessToken || isAdmin === false) {
    return (
      <main className="flex min-h-screen items-center justify-center p-4">
        <p className="text-muted-foreground">Перенаправление…</p>
      </main>
    );
  }

  return (
    <>
      <AppNav />
      <main className="mx-auto max-w-7xl px-4 py-8 pb-24 md:pb-8">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight">Журнал запросов</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Мониторинг и диагностика операций сервиса
          </p>
        </div>

        <Tabs>
          <TabsList>
            <TabsTrigger
              active={activeTab === "journal"}
              onClick={() => setActiveTab("journal")}
            >
              Журнал
            </TabsTrigger>
            <TabsTrigger
              active={activeTab === "errors"}
              onClick={() => setActiveTab("errors")}
            >
              Ошибки
            </TabsTrigger>
            <TabsTrigger
              active={activeTab === "analytics"}
              onClick={() => setActiveTab("analytics")}
            >
              Аналитика
            </TabsTrigger>
          </TabsList>

          <TabsContent>
            {activeTab === "journal" && <JournalTab />}
            {activeTab === "errors" && <ErrorsTab />}
            {activeTab === "analytics" && <AnalyticsTab />}
          </TabsContent>
        </Tabs>
      </main>
    </>
  );
}
