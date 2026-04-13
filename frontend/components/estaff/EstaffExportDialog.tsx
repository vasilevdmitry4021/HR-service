"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ApiError,
  ESTAFF_LAST_USER_LOGIN_STORAGE_KEY,
  ESTAFF_LAST_VACANCY_STORAGE_KEY,
  estaffLlmAnalysisHasPayload,
  fetchEstaffVacancies,
  postEstaffExport,
  postEstaffUserCheck,
  sanitizeApiErrorMessage,
  type EstaffExportResult,
  type EstaffHrBundleContext,
  type EstaffVacancyItem,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/** Совпадает с лимитом на сервере POST /estaff/export */
const MAX_RESUMES_PER_EXPORT = 50;

export type EstaffExportDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  resumeIds: string[];
  /** По умолчанию true — показ sonner-тостов после выгрузки */
  showToastNotifications?: boolean;
  /** Дополнительные поля по ключу кандидата (тот же id, что уходит в выгрузку) */
  hrBundleContextByResumeId?: Record<string, EstaffHrBundleContext>;
  onSuccess?: (summary?: {
    succeeded: number;
    failed: number;
    results: EstaffExportResult[];
  }) => void;
};

function currentYearDateBounds() {
  const y = new Date().getFullYear();
  return { from: `${y}-01-01`, to: `${y}-12-31` };
}

export function EstaffExportDialog({
  open,
  onOpenChange,
  resumeIds,
  showToastNotifications = true,
  hrBundleContextByResumeId,
  onSuccess,
}: EstaffExportDialogProps) {
  const [loadingList, setLoadingList] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [items, setItems] = useState<EstaffVacancyItem[]>([]);
  const [query, setQuery] = useState("");
  const [dateFrom, setDateFrom] = useState(() => currentYearDateBounds().from);
  const [dateTo, setDateTo] = useState(() => currentYearDateBounds().to);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [login, setLogin] = useState("");
  const [isLoginChecking, setIsLoginChecking] = useState(false);
  const [isLoginValid, setIsLoginValid] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [lastCheckedLogin, setLastCheckedLogin] = useState<string | null>(null);
  const loginCheckRequestIdRef = useRef(0);
  const loginValueRef = useRef("");

  const dateRangeInvalid =
    !dateFrom.trim() ||
    !dateTo.trim() ||
    dateFrom > dateTo;
  const normalizedLogin = login.trim();

  useEffect(() => {
    loginValueRef.current = normalizedLogin;
  }, [normalizedLogin]);

  const checkLogin = useCallback(async (rawLogin: string) => {
    const nextLogin = rawLogin.trim();
    if (!nextLogin) {
      setIsLoginValid(false);
      setLoginError("Укажите логин e-staff.");
      setLastCheckedLogin(null);
      return;
    }
    const requestId = loginCheckRequestIdRef.current + 1;
    loginCheckRequestIdRef.current = requestId;
    setIsLoginChecking(true);
    setLoginError(null);
    try {
      const res = await postEstaffUserCheck(nextLogin);
      if (
        requestId !== loginCheckRequestIdRef.current ||
        loginValueRef.current !== nextLogin
      ) {
        return;
      }
      setLastCheckedLogin(nextLogin);
      setIsLoginValid(res.valid);
      if (res.valid) {
        setLoginError(null);
        try {
          window.localStorage.setItem(ESTAFF_LAST_USER_LOGIN_STORAGE_KEY, nextLogin);
        } catch {
          /* ignore */
        }
      } else {
        setLoginError("Пользователь с таким логином не найден в e-staff.");
      }
    } catch (e) {
      if (
        requestId !== loginCheckRequestIdRef.current ||
        loginValueRef.current !== nextLogin
      ) {
        return;
      }
      const message =
        e instanceof ApiError
          ? sanitizeApiErrorMessage(e.message)
          : "Не удалось проверить логин e-staff.";
      setIsLoginValid(false);
      setLastCheckedLogin(nextLogin);
      setLoginError(message);
    } finally {
      if (
        requestId === loginCheckRequestIdRef.current &&
        loginValueRef.current === nextLogin
      ) {
        setIsLoginChecking(false);
      }
    }
  }, []);

  const resetLoginValidationState = useCallback(() => {
    // Инвалидируем текущий запрос, чтобы его результат не применился.
    loginCheckRequestIdRef.current += 1;
    setIsLoginChecking(false);
    setIsLoginValid(false);
    setLoginError(null);
    setLastCheckedLogin(null);
  }, []);

  const handleLoginInputChange = useCallback(
    (nextValue: string) => {
      setLogin(nextValue);
      resetLoginValidationState();
    },
    [resetLoginValidationState],
  );

  const triggerImmediateLoginCheck = useCallback(
    (rawLogin: string) => {
      const next = rawLogin.trim();
      if (!next) return;
      void checkLogin(next);
    },
    [checkLogin],
  );

  const loadVacancies = useCallback(async (from: string, to: string) => {
    if (!from.trim() || !to.trim() || from > to) {
      setListError(
        "Укажите корректный период: дата «с» не позже даты «по».",
      );
      return;
    }
    setLoadingList(true);
    setListError(null);
    setExportError(null);
    try {
      const data = await fetchEstaffVacancies(from.trim(), to.trim());
      setItems(data.items);
      const raw =
        typeof window !== "undefined"
          ? window.localStorage.getItem(ESTAFF_LAST_VACANCY_STORAGE_KEY)
          : null;
      const last = raw?.trim() || null;
      if (last && data.items.some((v) => v.id === last)) {
        setSelectedId(last);
      } else {
        setSelectedId(null);
      }
    } catch (e) {
      setItems([]);
      setSelectedId(null);
      setListError(
        e instanceof ApiError ? e.message : "Не удалось загрузить вакансии",
      );
    } finally {
      setLoadingList(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    const { from, to } = currentYearDateBounds();
    setDateFrom(from);
    setDateTo(to);
    setExportError(null);
    setIsLoginValid(false);
    setIsLoginChecking(false);
    setLoginError(null);
    setLastCheckedLogin(null);
    let cachedLogin = "";
    try {
      cachedLogin =
        window.localStorage.getItem(ESTAFF_LAST_USER_LOGIN_STORAGE_KEY)?.trim() ?? "";
    } catch {
      cachedLogin = "";
    }
    setLogin(cachedLogin);
    void loadVacancies(from, to);
    if (cachedLogin) {
      void checkLogin(cachedLogin);
    }
  }, [open, checkLogin, loadVacancies]);

  useEffect(() => {
    if (!open) return;
    if (!normalizedLogin) {
      setIsLoginChecking(false);
      setIsLoginValid(false);
      setLoginError(null);
      setLastCheckedLogin(null);
      return;
    }
    if (isLoginValid && lastCheckedLogin === normalizedLogin) {
      return;
    }
    if (isLoginChecking) {
      return;
    }
    const handle = window.setTimeout(() => {
      void checkLogin(normalizedLogin);
    }, 5000);
    return () => window.clearTimeout(handle);
  }, [
    checkLogin,
    isLoginChecking,
    isLoginValid,
    lastCheckedLogin,
    normalizedLogin,
    open,
  ]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onOpenChange(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((v) => {
      const t = `${v.title} ${v.subtitle ?? ""}`.toLowerCase();
      return t.includes(q);
    });
  }, [items, query]);

  const idsFiltered = useMemo(
    () => resumeIds.map((id) => id.trim()).filter(Boolean),
    [resumeIds],
  );
  const count = idsFiltered.length;
  const overLimit = count > MAX_RESUMES_PER_EXPORT;
  const canExportWithLogin =
    isLoginValid &&
    !isLoginChecking &&
    normalizedLogin.length > 0 &&
    lastCheckedLogin === normalizedLogin;

  const runExport = async () => {
    if (!selectedId || count === 0 || overLimit || !canExportWithLogin) return;
    setExporting(true);
    setExportError(null);
    try {
      const res = await postEstaffExport(
        idsFiltered.map((candidate_id) => {
          const ctx = hrBundleContextByResumeId?.[candidate_id];
          return {
            candidate_id,
            vacancy_id: selectedId,
            include_hr_llm_bundle: true,
            ...(ctx?.hr_llm_summary != null && ctx.hr_llm_summary !== ""
              ? { hr_llm_summary: ctx.hr_llm_summary }
              : {}),
            ...(ctx?.hr_llm_score != null
              ? { hr_llm_score: ctx.hr_llm_score }
              : {}),
            ...(ctx?.hr_llm_analysis != null &&
            estaffLlmAnalysisHasPayload(ctx.hr_llm_analysis)
              ? { hr_llm_analysis: ctx.hr_llm_analysis }
              : {}),
            ...(ctx?.hr_search_query != null &&
            ctx.hr_search_query.trim() !== ""
              ? { hr_search_query: ctx.hr_search_query.trim() }
              : {}),
          };
        }),
        normalizedLogin,
      );
      const results = res.results;
      const succeeded = results.filter((r) => r.status === "success").length;
      const failed = results.length - succeeded;
      try {
        window.localStorage.setItem(ESTAFF_LAST_VACANCY_STORAGE_KEY, selectedId);
      } catch {
        /* ignore */
      }
      onOpenChange(false);

      if (showToastNotifications) {
        if (results.length === 1) {
          const r = results[0];
          if (r.status === "success") {
            const warn = r.preparation_warnings?.filter(Boolean) ?? [];
            if (warn.length) {
              toast.success("Выгрузка в e-staff выполнена", {
                description: warn.slice(0, 5).join(" · "),
              });
            } else {
              toast.success("Выгрузка в e-staff выполнена");
            }
          } else {
            const stage =
              r.error_stage === "fetch_resume"
                ? "не удалось получить резюме"
                : r.error_stage === "preparation"
                  ? "ошибка подготовки данных"
                  : r.error_stage === "estaff_api"
                    ? "отказ e-staff"
                    : null;
            const base = sanitizeApiErrorMessage(r.error_message);
            toast.error(stage ? `${base} (${stage})` : base);
          }
        } else {
          toast.success(
            `Выгрузка завершена: успешно ${succeeded}, с ошибкой ${failed}.`,
          );
          if (failed > 0) {
            const firstErr = results.find((x) => x.status !== "success");
            if (firstErr?.error_message) {
              toast.message("Пример ошибки", {
                description: sanitizeApiErrorMessage(firstErr.error_message),
              });
            }
          }
        }
      }

      onSuccess?.({ succeeded, failed, results });
    } catch (e) {
      const raw =
        e instanceof ApiError ? e.message : "Не удалось выполнить выгрузку";
      if (showToastNotifications) {
        toast.error(sanitizeApiErrorMessage(raw));
      }
      setExportError("Выгрузка не удалась");
    } finally {
      setExporting(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50" role="presentation">
      <button
        type="button"
        aria-label="Закрыть"
        className="absolute inset-0 bg-black/50 animate-in fade-in duration-200"
        onClick={() => onOpenChange(false)}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="estaff-export-dialog-title"
        className={cn(
          "absolute left-1/2 top-1/2 max-h-[min(90vh,640px)] w-[calc(100%-2rem)] max-w-lg",
          "-translate-x-1/2 -translate-y-1/2 outline-none",
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <Card className="flex max-h-[min(90vh,640px)] flex-col shadow-lg">
          <CardHeader className="shrink-0 border-b pb-4">
            <CardTitle id="estaff-export-dialog-title">
              Выгрузка в e-staff
              {count > 1 ? ` (${count} резюме)` : null}
            </CardTitle>
            <p className="text-sm font-normal text-muted-foreground">
              Выберите вакансию в e-staff. Без выбора выгрузка недоступна. За один
              раз не более {MAX_RESUMES_PER_EXPORT} резюме (ограничение сервера).
            </p>
          </CardHeader>
          <CardContent className="flex min-h-0 flex-1 flex-col overflow-hidden pt-4">
            <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-1">
              <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="estaff-vac-date-from">Дата открытия с</Label>
                <Input
                  id="estaff-vac-date-from"
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  disabled={loadingList || exporting}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="estaff-vac-date-to">по</Label>
                <Input
                  id="estaff-vac-date-to"
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  disabled={loadingList || exporting}
                />
              </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="estaff-user-login">Логин e-staff</Label>
                <Input
                  id="estaff-user-login"
                  value={login}
                  onChange={(e) => handleLoginInputChange(e.target.value)}
                  onPaste={(e) => {
                    const input = e.currentTarget;
                    window.setTimeout(() => {
                      const pastedValue = input.value;
                      handleLoginInputChange(pastedValue);
                      triggerImmediateLoginCheck(pastedValue);
                    }, 0);
                  }}
                  onBlur={() => {
                    triggerImmediateLoginCheck(login);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      triggerImmediateLoginCheck(login);
                    }
                  }}
                  placeholder="Введите логин пользователя в e-staff"
                  autoComplete="off"
                  disabled={exporting}
                />
                {isLoginChecking ? (
                  <p className="text-xs text-muted-foreground">Проверяем логин…</p>
                ) : null}
                {!isLoginChecking &&
                isLoginValid &&
                lastCheckedLogin === normalizedLogin ? (
                  <p className="text-xs text-emerald-600 dark:text-emerald-400">
                    Логин подтвержден.
                  </p>
                ) : null}
                {!isLoginChecking && loginError ? (
                  <p className="text-xs text-destructive">{loginError}</p>
                ) : null}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  disabled={loadingList || exporting || dateRangeInvalid}
                  onClick={() => void loadVacancies(dateFrom, dateTo)}
                >
                  Обновить список
                </Button>
                {dateRangeInvalid ? (
                  <p className="text-sm text-muted-foreground">
                    Задайте обе даты; «с» не позже «по».
                  </p>
                ) : null}
              </div>

              {loadingList ? (
                <p className="text-sm text-muted-foreground">Загрузка списка…</p>
              ) : null}

              {listError ? (
                <p className="text-sm text-destructive">{listError}</p>
              ) : null}

              {!loadingList && !listError && items.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Список вакансий пуст. Создайте вакансию в e-staff или проверьте
                  путь API (ESTAFF_VACANCIES_PATH) на сервере.
                </p>
              ) : null}

              {!loadingList && !listError && items.length > 0 ? (
                <div className="flex min-h-0 flex-1 flex-col gap-2">
                  <Label htmlFor="estaff-vac-search">Поиск по названию</Label>
                  <Input
                    id="estaff-vac-search"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Начните вводить название…"
                    autoComplete="off"
                  />
                  <div
                    className="min-h-0 flex-1 overflow-y-auto rounded-md border border-border"
                    role="listbox"
                    aria-label="Вакансии e-staff"
                  >
                    {filtered.length === 0 ? (
                      <p className="p-3 text-sm text-muted-foreground">
                        Ничего не найдено. Измените запрос.
                      </p>
                    ) : (
                      <ul className="divide-y divide-border p-1">
                        {filtered.map((v) => {
                          const selected = selectedId === v.id;
                          return (
                            <li key={v.id}>
                              <button
                                type="button"
                                role="option"
                                aria-selected={selected}
                                className={cn(
                                  "w-full rounded-sm px-3 py-2.5 text-left text-sm transition-colors",
                                  "hover:bg-muted/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                                  selected && "bg-muted",
                                )}
                                onClick={() => setSelectedId(v.id)}
                              >
                                <span className="font-medium">{v.title}</span>
                                {v.subtitle ? (
                                  <span className="mt-0.5 block text-xs text-muted-foreground">
                                    {v.subtitle}
                                  </span>
                                ) : null}
                              </button>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </div>
                </div>
              ) : null}

              {exportError ? (
                <p className="text-sm text-destructive">{exportError}</p>
              ) : null}

              {overLimit ? (
                <p className="text-sm text-destructive">
                  Слишком много резюме ({count}). Уменьшите выбор до{" "}
                  {MAX_RESUMES_PER_EXPORT} или выгрузите частями.
                </p>
              ) : null}
            </div>

            <div className="mt-2 flex shrink-0 flex-wrap justify-end gap-2 border-t border-border pt-2">
              <Button
                type="button"
                variant="secondary"
                onClick={() => onOpenChange(false)}
                disabled={exporting}
              >
                Отмена
              </Button>
              <Button
                type="button"
                onClick={() => void runExport()}
                disabled={
                  exporting ||
                  !selectedId ||
                  count === 0 ||
                  overLimit ||
                  loadingList ||
                  !!listError ||
                  !canExportWithLogin
                }
              >
                {exporting ? "Выгрузка…" : "Выгрузить в e-staff"}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
