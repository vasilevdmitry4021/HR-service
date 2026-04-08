"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { AppNav } from "@/components/AppNav";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ApiError,
  deleteTelegramSource,
  fetchTelegramSources,
  fetchTelegramStatus,
  fetchTelegramSyncRuns,
  patchTelegramSource,
  postTelegramConnect,
  postTelegramDisconnect,
  postTelegramSource,
  postTelegramSyncSource,
  postTelegramValidateSource,
  postTelegramVerify,
  postTelegramVerifyPassword,
  sanitizeApiErrorMessage,
  type TelegramSourceRow,
  type TelegramStatusResponse,
  type TelegramSyncRunRow,
} from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";

const RUN_STATUS_LABELS: Record<string, string> = {
  queued: "Ожидает запуска",
  running: "Идёт синхронизация",
  completed: "Завершено",
  failed: "Ошибка",
};

const ACCESS_STATUS_LABELS: Record<string, string> = {
  active: "доступ подтверждён",
  unavailable: "временно недоступен",
  access_required: "нужен доступ через аккаунт Telegram",
  invalid: "ссылка заполнена с ошибкой",
};

function humanizeRunStatus(status: string) {
  return RUN_STATUS_LABELS[status] ?? status;
}

function humanizeAccessStatus(status: string) {
  return ACCESS_STATUS_LABELS[status] ?? status;
}

function explainSyncError(raw: unknown): string | null {
  if (typeof raw !== "string" || !raw.trim()) {
    return null;
  }
  const msg = raw.trim();
  if (msg.includes("Could not find the input entity for PeerChannel")) {
    return "Сервис не смог открыть канал через текущий Telegram-аккаунт. Обычно это происходит, если аккаунт не вступал в канал или ещё не открывал его в Telegram.";
  }
  if (msg.includes("Сессия Telegram не авторизована")) {
    return "Сессия Telegram истекла. Подключите аккаунт заново.";
  }
  return msg;
}

export default function TelegramSettingsPage() {
  const router = useRouter();
  const accessToken = useAuthStore((s) => s.accessToken);
  const hasHydrated = useAuthStore((s) => s._hasHydrated);
  const [status, setStatus] = useState<TelegramStatusResponse | null>(null);
  const [sources, setSources] = useState<TelegramSourceRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiId, setApiId] = useState("");
  const [apiHash, setApiHash] = useState("");
  const [phone, setPhone] = useState("");
  const [accountId, setAccountId] = useState<string | null>(null);
  const [needTwoFactor, setNeedTwoFactor] = useState(false);
  const [code, setCode] = useState("");
  const [twoFactorPassword, setTwoFactorPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [srcLink, setSrcLink] = useState("");
  const [srcName, setSrcName] = useState("");
  const [srcTgId, setSrcTgId] = useState("");
  const [syncRuns, setSyncRuns] = useState<TelegramSyncRunRow[]>([]);
  const [pendingSyncSourceId, setPendingSyncSourceId] = useState<string | null>(
    null,
  );

  const refresh = useCallback(async () => {
    const s = await fetchTelegramStatus();
    setStatus(s);
    if (!s.feature_enabled) {
      setSources([]);
      setSyncRuns([]);
      return;
    }
    if (s.connected) {
      setAccountId(null);
      setNeedTwoFactor(false);
      setCode("");
      setTwoFactorPassword("");
    } else if (s.account_id && s.auth_status === "pending") {
      setAccountId(s.account_id);
      setNeedTwoFactor(!!s.awaiting_two_factor);
    } else {
      setAccountId(null);
      setNeedTwoFactor(false);
      setCode("");
      setTwoFactorPassword("");
    }
    if (s.connected) {
      const list = await fetchTelegramSources();
      setSources(list);
      try {
        const runs = await fetchTelegramSyncRuns(30);
        setSyncRuns(runs);
      } catch {
        setSyncRuns([]);
      }
    } else {
      setSources([]);
      setSyncRuns([]);
    }
  }, []);

  useEffect(() => {
    if (!hasHydrated) return;
    if (!accessToken) {
      router.replace("/login");
      return;
    }
    setLoading(true);
    void refresh()
      .catch(() => {
        setStatus({ feature_enabled: false, connected: false });
        setSources([]);
      })
      .finally(() => setLoading(false));
  }, [hasHydrated, accessToken, router, refresh]);

  const hasActiveSyncRun = syncRuns.some(
    (run) => run.status === "queued" || run.status === "running",
  );

  useEffect(() => {
    if (!status?.connected) return;
    if (!hasActiveSyncRun && !pendingSyncSourceId) return;
    const timerId = window.setInterval(() => {
      void refresh().catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timerId);
  }, [hasActiveSyncRun, pendingSyncSourceId, refresh, status?.connected]);

  useEffect(() => {
    if (!pendingSyncSourceId) return;
    const latestRun = syncRuns.find((run) => run.source_id === pendingSyncSourceId);
    if (!latestRun) return;
    if (latestRun.status === "completed" || latestRun.status === "failed") {
      setPendingSyncSourceId(null);
    }
  }, [pendingSyncSourceId, syncRuns]);

  const sourceNameById = new Map(sources.map((source) => [source.id, source.display_name]));
  const latestRunBySource = new Map<string, TelegramSyncRunRow>();
  for (const run of syncRuns) {
    if (!latestRunBySource.has(run.source_id)) {
      latestRunBySource.set(run.source_id, run);
    }
  }

  if (!hasHydrated || !accessToken) {
    return (
      <main className="flex min-h-screen items-center justify-center p-4">
        <p className="text-muted-foreground">Загрузка…</p>
      </main>
    );
  }

  return (
    <>
      <AppNav />
      <main className="mx-auto max-w-4xl space-y-8 px-4 py-6 lg:px-6 lg:py-10">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h1 className="text-3xl font-display font-bold tracking-tight">Интеграция с Telegram</h1>
          <Link href="/settings" className="text-sm text-primary font-medium hover:underline">
            ← Назад к настройкам
          </Link>
        </div>

        {loading ? (
          <div className="flex items-center gap-3 text-muted-foreground">
            <div className="h-1 w-1 rounded-full bg-primary animate-pulse" />
            <p className="text-sm">Загрузка конфигурации...</p>
          </div>
        ) : status && !status.feature_enabled ? (
          <Card>
            <CardHeader>
              <CardTitle>Функция недоступна</CardTitle>
              <CardDescription>
                Интеграция с Telegram отключена в конфигурации сервера.
                Обратитесь к администратору для активации.
              </CardDescription>
            </CardHeader>
          </Card>
        ) : (
          <>
            <Card>
              <CardHeader>
                <CardTitle>Статус</CardTitle>
                <CardDescription>
                  {status?.connected
                    ? `Подключено${status.phone_hint ? ` (${status.phone_hint})` : ""}${
                        status.last_sync_at
                          ? `. Последняя синхронизация по аккаунту: ${new Date(
                              status.last_sync_at,
                            ).toLocaleString()}`
                          : ""
                      }`
                    : "Аккаунт не подключён"}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {status?.connected ? (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={busy}
                    onClick={() => {
                      setBusy(true);
                      void postTelegramDisconnect()
                        .then(() => {
                          toast.success("Отключено");
                          return refresh();
                        })
                        .catch((e) =>
                          toast.error(
                            sanitizeApiErrorMessage(
                              e instanceof ApiError ? e.message : String(e),
                            ),
                          ),
                        )
                        .finally(() => setBusy(false));
                    }}
                  >
                    Отключить Telegram
                  </Button>
                ) : (
                  <div className="space-y-3">
                    <div className="rounded-md border border-border bg-muted/40 px-3 py-2.5 text-sm text-muted-foreground">
                      <p className="font-medium text-foreground">
                        Откуда взять api_id и api_hash
                      </p>
                      <ol className="mt-2 list-decimal space-y-1.5 pl-5">
                        <li>
                          Откройте официальный сайт{" "}
                          <a
                            href="https://my.telegram.org"
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-primary underline"
                          >
                            my.telegram.org
                          </a>{" "}
                          и войдите по номеру телефона, привязанному к Telegram.
                        </li>
                        <li>
                          Перейдите в раздел «API development tools» и создайте
                          приложение (достаточно указать произвольное название и
                          краткое описание).
                        </li>
                        <li>
                          Скопируйте выданные{" "}
                          <span className="font-mono text-xs">api_id</span> и{" "}
                          <span className="font-mono text-xs">api_hash</span> в
                          поля ниже. Эти данные не передавайте посторонним.
                        </li>
                      </ol>
                      <p className="mt-2">
                        В поле телефона укажите тот же номер, с которым вы
                        заходите в Telegram (с кодом страны, например +7…).
                      </p>
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="tg-api-id">api_id</Label>
                      <Input
                        id="tg-api-id"
                        value={apiId}
                        onChange={(e) => setApiId(e.target.value)}
                        autoComplete="off"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="tg-api-hash">api_hash</Label>
                      <Input
                        id="tg-api-hash"
                        type="password"
                        value={apiHash}
                        onChange={(e) => setApiHash(e.target.value)}
                        autoComplete="off"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="tg-phone">Телефон (с кодом страны)</Label>
                      <Input
                        id="tg-phone"
                        value={phone}
                        onChange={(e) => setPhone(e.target.value)}
                        placeholder="+79991234567"
                        autoComplete="tel"
                      />
                    </div>
                    <Button
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        setBusy(true);
                        void postTelegramConnect({
                          api_id: apiId.trim(),
                          api_hash: apiHash.trim(),
                          phone: phone.trim(),
                        })
                          .then((r) => {
                            setAccountId(r.account_id);
                            setNeedTwoFactor(false);
                            toast.success("Код отправлен");
                          })
                          .catch((e) =>
                            toast.error(
                              sanitizeApiErrorMessage(
                                e instanceof ApiError ? e.message : String(e),
                              ),
                            ),
                          )
                          .finally(() => setBusy(false));
                      }}
                    >
                      Запросить код
                    </Button>
                    {accountId ? (
                      <div className="space-y-2 border-t pt-3">
                        {!needTwoFactor ? (
                          <>
                            <Label htmlFor="tg-code">Код из Telegram / SMS</Label>
                            <Input
                              id="tg-code"
                              value={code}
                              onChange={(e) => setCode(e.target.value)}
                              autoComplete="one-time-code"
                            />
                            <Button
                              type="button"
                              disabled={busy}
                              onClick={() => {
                                setBusy(true);
                                void postTelegramVerify({
                                  account_id: accountId,
                                  code: code.trim(),
                                })
                                  .then((r) => {
                                    if (r.status === "need_password") {
                                      setNeedTwoFactor(true);
                                      setCode("");
                                      toast.message(
                                        r.message ??
                                          "Введите облачный пароль двухэтапной проверки Telegram.",
                                      );
                                      return;
                                    }
                                    toast.success("Подключено");
                                    setCode("");
                                    setAccountId(null);
                                    return refresh();
                                  })
                                  .catch((e) =>
                                    toast.error(
                                      sanitizeApiErrorMessage(
                                        e instanceof ApiError ? e.message : String(e),
                                      ),
                                    ),
                                  )
                                  .finally(() => setBusy(false));
                              }}
                            >
                              Подтвердить код
                            </Button>
                          </>
                        ) : (
                          <>
                            <p className="text-sm text-muted-foreground">
                              У аккаунта включена двухэтапная проверка. Укажите облачный пароль
                              из настроек Telegram (Конфиденциальность).
                            </p>
                            <Label htmlFor="tg-2fa-pw">Облачный пароль</Label>
                            <Input
                              id="tg-2fa-pw"
                              type="password"
                              value={twoFactorPassword}
                              onChange={(e) => setTwoFactorPassword(e.target.value)}
                              autoComplete="current-password"
                            />
                            <Button
                              type="button"
                              disabled={busy}
                              onClick={() => {
                                setBusy(true);
                                void postTelegramVerifyPassword({
                                  account_id: accountId,
                                  password: twoFactorPassword.trim(),
                                })
                                  .then(() => {
                                    toast.success("Подключено");
                                    setTwoFactorPassword("");
                                    setAccountId(null);
                                    setNeedTwoFactor(false);
                                    return refresh();
                                  })
                                  .catch((e) =>
                                    toast.error(
                                      sanitizeApiErrorMessage(
                                        e instanceof ApiError ? e.message : String(e),
                                      ),
                                    ),
                                  )
                                  .finally(() => setBusy(false));
                              }}
                            >
                              Подтвердить пароль
                            </Button>
                          </>
                        )}
                      </div>
                    ) : null}
                  </div>
                )}
              </CardContent>
            </Card>

            {status?.connected ? (
              <Card>
                <CardHeader>
                  <CardTitle>Источники</CardTitle>
                  <CardDescription>
                    Каналы и чаты для сбора сообщений. После запуска синхронизации
                    статус ниже обновляется автоматически.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid gap-2 sm:grid-cols-2">
                    <div className="space-y-1 sm:col-span-2">
                      <Label htmlFor="src-link">Ссылка или @username</Label>
                      <Input
                        id="src-link"
                        value={srcLink}
                        onChange={(e) => setSrcLink(e.target.value)}
                        placeholder="https://t.me/..."
                      />
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="src-name">Название</Label>
                      <Input
                        id="src-name"
                        value={srcName}
                        onChange={(e) => setSrcName(e.target.value)}
                      />
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="src-tg-id">telegram_id (необязательно)</Label>
                      <Input
                        id="src-tg-id"
                        value={srcTgId}
                        onChange={(e) => setSrcTgId(e.target.value)}
                        inputMode="numeric"
                      />
                    </div>
                  </div>
                  <Button
                    type="button"
                    disabled={busy || !srcLink.trim()}
                    onClick={() => {
                      setBusy(true);
                      const tid = srcTgId.trim()
                        ? parseInt(srcTgId.trim(), 10)
                        : undefined;
                      void postTelegramSource({
                        link: srcLink.trim(),
                        display_name: srcName.trim(),
                        telegram_id:
                          tid != null && !Number.isNaN(tid) ? tid : undefined,
                      })
                        .then(() => {
                          setSrcLink("");
                          setSrcName("");
                          setSrcTgId("");
                          toast.success("Источник добавлен");
                          return refresh();
                        })
                        .catch((e) =>
                          toast.error(
                            sanitizeApiErrorMessage(
                              e instanceof ApiError ? e.message : String(e),
                            ),
                          ),
                        )
                        .finally(() => setBusy(false));
                    }}
                  >
                    Добавить источник
                  </Button>

                  <ul className="space-y-4">
                    {sources.map((s) => {
                      const latestRun = latestRunBySource.get(s.id);
                      const syncInProgress =
                        pendingSyncSourceId === s.id ||
                        latestRun?.status === "queued" ||
                        latestRun?.status === "running";
                      const latestError =
                        latestRun &&
                        latestRun.error_log &&
                        typeof latestRun.error_log === "object" &&
                        !Array.isArray(latestRun.error_log) &&
                        "error" in latestRun.error_log
                          ? explainSyncError(
                              (latestRun.error_log as { error?: unknown }).error,
                            )
                          : null;

                      return (
                        <li
                          key={s.id}
                          className="flex flex-col gap-3 rounded-xl border-2 bg-card p-4 shadow-sm transition-shadow hover:shadow-md sm:flex-row sm:items-center sm:justify-between"
                        >
                          <div className="min-w-0 space-y-1">
                            <p className="font-medium">{s.display_name}</p>
                            <p className="truncate text-xs text-muted-foreground">
                              {s.link}
                            </p>
                            <p className="text-xs text-muted-foreground">
                              Доступ: {humanizeAccessStatus(s.access_status)}. Источник{" "}
                              {s.is_enabled ? "включён" : "отключён"}.
                              {s.last_sync_at
                                ? ` Последняя успешная синхронизация: ${new Date(
                                    s.last_sync_at,
                                  ).toLocaleString()}.`
                                : ""}
                            </p>
                            <p className="text-xs text-muted-foreground">
                              Синхронизация:{" "}
                              {latestRun
                                ? `${humanizeRunStatus(latestRun.status)} с ${new Date(
                                    latestRun.started_at,
                                  ).toLocaleString()}`
                                : "ещё не запускалась"}
                              {syncInProgress
                                ? ". Обновляем статус автоматически."
                                : ""}
                            </p>
                            {s.access_status !== "active" ? (
                              <p className="text-xs text-amber-700">
                                Перед синхронизацией лучше сначала нажать
                                «Проверить доступ». Если аккаунт не имеет доступа к
                                каналу, загрузка не начнётся.
                              </p>
                            ) : null}
                            {s.error_message ? (
                              <p className="mt-1 text-xs text-destructive">
                                {explainSyncError(s.error_message) ?? s.error_message}
                              </p>
                            ) : null}
                            {!s.error_message && latestError ? (
                              <p className="mt-1 text-xs text-destructive">
                                {latestError}
                              </p>
                            ) : null}
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <Button
                              type="button"
                              size="sm"
                              variant="secondary"
                              disabled={busy || syncInProgress}
                              onClick={() => {
                                setBusy(true);
                                void postTelegramValidateSource(s.id)
                                  .then(() => {
                                    toast.success("Проверка выполнена");
                                    return refresh();
                                  })
                                  .catch((e) =>
                                    toast.error(
                                      sanitizeApiErrorMessage(
                                        e instanceof ApiError
                                          ? e.message
                                          : String(e),
                                      ),
                                    ),
                                  )
                                  .finally(() => setBusy(false));
                              }}
                            >
                              Проверить доступ
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="default"
                              disabled={busy || syncInProgress}
                              onClick={() => {
                                setBusy(true);
                                setPendingSyncSourceId(s.id);
                                void postTelegramSyncSource(s.id)
                                  .then((run) => {
                                    toast.success(
                                      run.status === "queued"
                                        ? "Запуск принят. Статус обновится автоматически."
                                        : "Синхронизация запущена.",
                                    );
                                    return refresh();
                                  })
                                  .catch((e) => {
                                    setPendingSyncSourceId(null);
                                    toast.error(
                                      sanitizeApiErrorMessage(
                                        e instanceof ApiError
                                          ? e.message
                                          : String(e),
                                      ),
                                    );
                                  })
                                  .finally(() => setBusy(false));
                              }}
                            >
                              {syncInProgress
                                ? latestRun?.status === "running"
                                  ? "Идёт синхронизация"
                                  : "Ожидает запуска"
                                : "Запустить синхронизацию"}
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              onClick={() => {
                                void patchTelegramSource(s.id, {
                                  is_enabled: !s.is_enabled,
                                })
                                  .then(() => refresh())
                                  .catch((e) =>
                                    toast.error(
                                      sanitizeApiErrorMessage(
                                        e instanceof ApiError
                                          ? e.message
                                          : String(e),
                                      ),
                                    ),
                                  );
                              }}
                            >
                              {s.is_enabled ? "Отключить" : "Включить"}
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="destructive"
                              onClick={() => {
                                void deleteTelegramSource(s.id)
                                  .then(() => {
                                    toast.success("Удалено");
                                    return refresh();
                                  })
                                  .catch((e) =>
                                    toast.error(
                                      sanitizeApiErrorMessage(
                                        e instanceof ApiError
                                          ? e.message
                                          : String(e),
                                      ),
                                    ),
                                  );
                              }}
                            >
                              Удалить
                            </Button>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                  {sources.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      Источников пока нет.
                    </p>
                  ) : null}
                </CardContent>
              </Card>
            ) : null}

            {status?.connected ? (
              <Card>
                <CardHeader>
                  <CardTitle>Недавние запуски синхронизации</CardTitle>
                  <CardDescription>
                    Состояние задач обработки сообщений по вашим источникам. Пока
                    есть ожидание или выполнение, список обновляется автоматически.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {syncRuns.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      Записей пока нет. Запустите синхронизацию у нужного
                      источника.
                    </p>
                  ) : (
                    <ul className="space-y-2 text-sm">
                      {syncRuns.map((r) => (
                        <li
                          key={r.id}
                          className="rounded-md border border-border px-3 py-2"
                        >
                          <p className="font-medium">
                            Состояние: {humanizeRunStatus(r.status)}
                            <span className="ml-2 font-normal text-muted-foreground">
                              {new Date(r.started_at).toLocaleString()}
                            </span>
                          </p>
                          <p className="text-xs text-muted-foreground">
                            Источник: {sourceNameById.get(r.source_id) ?? "Источник"} ·
                            Сообщений: {r.messages_processed} · Кандидатов:{" "}
                            {r.candidates_created}
                            {r.finished_at
                              ? ` · завершено ${new Date(
                                  r.finished_at,
                                ).toLocaleString()}`
                              : ""}
                          </p>
                          {r.error_log != null &&
                          r.error_log !== undefined &&
                          (Array.isArray(r.error_log)
                            ? r.error_log.length > 0
                            : typeof r.error_log === "object" &&
                              r.error_log !== null &&
                              Object.keys(r.error_log as object).length > 0) ? (
                            <p className="mt-1 text-xs text-destructive">
                              {typeof r.error_log === "object" &&
                              r.error_log !== null &&
                              "error" in r.error_log
                                ? explainSyncError(
                                    (r.error_log as { error?: unknown }).error,
                                  ) ??
                                  String(
                                    (r.error_log as { error?: unknown }).error,
                                  )
                                : JSON.stringify(r.error_log).slice(0, 400)}
                            </p>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>
            ) : null}
          </>
        )}
      </main>
    </>
  );
}
