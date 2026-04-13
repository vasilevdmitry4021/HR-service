"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { AppNav } from "@/components/AppNav";
import { StatusIndicator } from "@/components/StatusIndicator";
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
  apiFetch,
  fetchEstaffCredentialsStatus,
  fetchLLMSettingsStatus,
  putEstaffCredentials,
  testLLMConnection,
  updateLLMSettings,
  type LLMProvider,
  type LLMSettingsIn,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";

let hhOAuthInflightCode: string | null = null;

function isLlmProvider(v: string): v is LLMProvider {
  return (
    v === "ollama" ||
    v === "openai_compatible" ||
    v === "yandex_gpt" ||
    v === "gigachat"
  );
}

function SettingsNotice({
  msg,
  err,
}: {
  msg: string | null;
  err: string | null;
}) {
  return (
    <>
      {msg ? (
        <div className="rounded-lg border-2 border-success/30 bg-success/10 px-4 py-3 text-sm text-success animate-fade-in">
          {msg}
        </div>
      ) : null}
      {err ? (
        <div className="rounded-lg border-2 border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive animate-fade-in">
          {err}
        </div>
      ) : null}
    </>
  );
}

function SettingsBody() {
  const router = useRouter();
  const params = useSearchParams();
  const accessToken = useAuthStore((s) => s.accessToken);
  const canWriteIntegrationSettings = useAuthStore(
    (s) => s.canWriteIntegrationSettings,
  );
  const canManageIntegrationEditors = useAuthStore(
    (s) => s.canManageIntegrationEditors,
  );
  const hasHydrated = useAuthStore((s) => s._hasHydrated);
  const [llmMsg, setLlmMsg] = useState<string | null>(null);
  const [llmErr, setLlmErr] = useState<string | null>(null);
  const [estaffMsg, setEstaffMsg] = useState<string | null>(null);
  const [estaffErr, setEstaffErr] = useState<string | null>(null);
  const [hhMsg, setHhMsg] = useState<string | null>(null);
  const [hhErr, setHhErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [estaffConfigured, setEstaffConfigured] = useState(false);
  const [estaffServer, setEstaffServer] = useState("");
  const [estaffToken, setEstaffToken] = useState("");
  const [savingEstaff, setSavingEstaff] = useState(false);

  const [llmConfigured, setLlmConfigured] = useState(false);
  const [llmProvider, setLlmProvider] =
    useState<LLMProvider>("openai_compatible");
  const [llmEndpoint, setLlmEndpoint] = useState("");
  const [llmModel, setLlmModel] = useState("llama3.2");
  const [llmFastModel, setLlmFastModel] = useState("");
  const [llmApiKey, setLlmApiKey] = useState("");
  const [llmFolderId, setLlmFolderId] = useState("");
  const [llmClientId, setLlmClientId] = useState("");
  const [llmClientSecret, setLlmClientSecret] = useState("");
  const [llmScope, setLlmScope] = useState("");
  const [savingLlm, setSavingLlm] = useState(false);
  const [testingLlm, setTestingLlm] = useState(false);
  const [llmTestHint, setLlmTestHint] = useState<string | null>(null);
  const [llmManualOpen, setLlmManualOpen] = useState(false);

  useEffect(() => {
    if (!hasHydrated) return;
    if (!accessToken) router.replace("/login");
  }, [hasHydrated, accessToken, router]);

  useEffect(() => {
    if (!accessToken) return;
    if (canWriteIntegrationSettings !== true) return;
    void fetchEstaffCredentialsStatus()
      .then((st) => setEstaffConfigured(st.configured))
      .catch(() => {
        /* ignore */
      });
    void fetchLLMSettingsStatus()
      .then((st) => {
        setLlmConfigured(st.configured);
        if (st.provider && isLlmProvider(st.provider)) {
          setLlmProvider(st.provider);
        }
        setLlmEndpoint(st.endpoint ?? "");
        setLlmModel(st.model ?? "llama3.2");
        setLlmFastModel(st.fast_model ?? "");
        setLlmFolderId(st.folder_id ?? "");
        setLlmClientId(st.client_id ?? "");
        setLlmScope(st.scope ?? "");
      })
      .catch(() => {
        /* ignore */
      });
  }, [accessToken, canWriteIntegrationSettings]);

  async function saveLlmSettings() {
    setSavingLlm(true);
    setLlmErr(null);
    setLlmMsg(null);
    setLlmTestHint(null);
    try {
      const body: LLMSettingsIn = {
        provider: llmProvider,
        endpoint: llmEndpoint.trim() || null,
        model: llmModel.trim(),
        fast_model: llmFastModel.trim() || null,
        folder_id: llmFolderId.trim() || null,
        client_id: llmClientId.trim() || null,
        scope: llmScope.trim() || null,
      };
      if (llmApiKey.trim()) {
        body.api_key = llmApiKey.trim();
      }
      if (llmClientSecret.trim()) {
        body.client_secret = llmClientSecret.trim();
      }
      await updateLLMSettings(body);
      setLlmApiKey("");
      setLlmClientSecret("");
      setLlmMsg("Настройки языковой модели сохранены");
      const st = await fetchLLMSettingsStatus();
      setLlmConfigured(st.configured);
    } catch (e) {
      setLlmErr(
        e instanceof ApiError ? e.message : "Не удалось сохранить настройки LLM",
      );
    } finally {
      setSavingLlm(false);
    }
  }

  async function runLlmTest() {
    setTestingLlm(true);
    setLlmErr(null);
    setLlmTestHint(null);
    try {
      const r = await testLLMConnection();
      setLlmTestHint(
        `${r.success ? "Успешно" : "Сбой"}: ${r.message}` +
          (r.response_time_ms != null ? ` (${r.response_time_ms} мс)` : ""),
      );
    } catch (e) {
      setLlmErr(
        e instanceof ApiError ? e.message : "Не удалось проверить соединение",
      );
    } finally {
      setTestingLlm(false);
    }
  }

  const finishOAuth = useCallback(
    async (code: string, state: string | null) => {
      const key = `hh_oauth:${code}`;
      if (typeof window !== "undefined") {
        const prev = sessionStorage.getItem(key);
        if (prev === "done" || prev === "pending") return;
      }
      if (hhOAuthInflightCode === code) return;
      hhOAuthInflightCode = code;
      if (typeof window !== "undefined") {
        sessionStorage.setItem(key, "pending");
      }
      setBusy(true);
      setHhErr(null);
      setHhMsg(null);
      try {
        await apiFetch("/hh/connect", {
          method: "POST",
          body: JSON.stringify({
            code,
            state: state ?? undefined,
          }),
        });
        if (typeof window !== "undefined") {
          sessionStorage.setItem(`hh_oauth:${code}`, "done");
        }
        setHhMsg("HeadHunter подключён.");
        router.replace("/settings");
      } catch (e) {
        if (typeof window !== "undefined") {
          sessionStorage.removeItem(`hh_oauth:${code}`);
        }
        setHhErr(e instanceof ApiError ? e.message : "Ошибка подключения");
      } finally {
        if (hhOAuthInflightCode === code) hhOAuthInflightCode = null;
        setBusy(false);
      }
    },
    [router],
  );

  useEffect(() => {
    const code = params.get("code");
    const state = params.get("state");
    if (!code || !accessToken) return;
    void finishOAuth(code, state);
  }, [params, accessToken, finishOAuth]);

  useEffect(() => {
    if (!accessToken) return;
    const oauth = params.get("hh_oauth");
    if (!oauth) return;
    setHhErr(null);
    setHhMsg(null);
    if (oauth === "ok") {
      setHhMsg("HeadHunter подключён.");
    } else if (oauth === "error") {
      const m = params.get("hh_msg");
      setHhErr(
        m
          ? decodeURIComponent(m.replace(/\+/g, " "))
          : "Ошибка подключения HeadHunter",
      );
    }
    router.replace("/settings");
  }, [params, accessToken, router]);

  async function saveEstaffCredentials() {
    setSavingEstaff(true);
    setEstaffErr(null);
    setEstaffMsg(null);
    try {
      await putEstaffCredentials(estaffServer.trim(), estaffToken.trim());
      setEstaffConfigured(true);
      setEstaffServer("");
      setEstaffToken("");
      setEstaffMsg("Настройки e-staff сохранены");
      const st = await fetchEstaffCredentialsStatus();
      setEstaffConfigured(st.configured);
    } catch (e) {
      setEstaffErr(
        e instanceof ApiError ? e.message : "Не удалось сохранить e-staff",
      );
    } finally {
      setSavingEstaff(false);
    }
  }

  async function startConnect() {
    setHhErr(null);
    setBusy(true);
    try {
      const data = await apiFetch<{ authorization_url: string }>(
        "/hh/connect",
        { method: "GET" },
      );
      window.location.href = data.authorization_url;
    } catch (e) {
      setHhErr(
        e instanceof ApiError ? e.message : "Не удалось запустить OAuth",
      );
      setBusy(false);
    }
  }

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

  if (canWriteIntegrationSettings === null) {
    return (
      <>
        <AppNav />
        <main className="mx-auto w-full max-w-7xl px-4 py-6 lg:px-6 lg:py-10">
          <p className="text-muted-foreground">Загрузка профиля…</p>
        </main>
      </>
    );
  }

  const llmSelectClass = cn(
    "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm",
    "ring-offset-background text-foreground",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
    "disabled:cursor-not-allowed disabled:opacity-50",
  );

  return (
    <>
      <AppNav />
      <main className="mx-auto w-full max-w-7xl space-y-8 px-4 py-6 lg:px-6 lg:py-10">
        <div className="flex items-center justify-between gap-4">
          <h1 className="text-3xl font-display font-bold tracking-tight">Настройки сервиса</h1>
          <StatusIndicator />
        </div>
        <div className="rounded-lg bg-muted/30 px-4 py-3 text-sm">
          <Link href="/settings/telegram" className="text-primary font-medium hover:underline">
            Перейти к настройкам Telegram →
          </Link>
        </div>

        {canManageIntegrationEditors === true ? (
          <div className="rounded-lg border border-border bg-card px-4 py-3 text-sm">
            <Link
              href="/settings/integration-editors"
              className="text-primary font-medium hover:underline"
            >
              Кто может менять глобальные настройки интеграций →
            </Link>
          </div>
        ) : null}

        {!canWriteIntegrationSettings ? (
          <Card>
            <CardHeader>
              <CardTitle>Глобальные интеграции</CardTitle>
              <CardDescription>
                Параметры подключения к языковой модели и e-staff.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm text-muted-foreground">
              <p>
                Изменять эти настройки может только администратор системы или
                сотрудник, которому администратор явно выдал такое право. Если вам
                нужен доступ, обратитесь к администратору.
              </p>
            </CardContent>
          </Card>
        ) : null}

        {canWriteIntegrationSettings ? (
        <div className="grid gap-6 xl:grid-cols-2">
          <Card className="xl:col-span-2 relative overflow-hidden">
            <div className="absolute top-0 right-0 w-32 h-32 bg-primary/5 rounded-full blur-3xl -translate-y-1/2 translate-x-1/2" />
            <CardHeader className="relative">
              <CardTitle>Языковая модель (LLM)</CardTitle>
              <div className="space-y-3 text-sm text-muted-foreground">
                <p>
                  Статус:{" "}
                  {llmConfigured
                    ? "подключение настроено"
                    : "не настроено или неполно"}
                  {llmEndpoint ? (
                    <>
                      . Кратко адрес:{" "}
                      <span className="break-all font-mono text-xs">
                        {(llmEndpoint.length > 40
                          ? `${llmEndpoint.slice(0, 36)}…`
                          : llmEndpoint) || "—"}
                      </span>
                    </>
                  ) : null}
                </p>
                <div
                  role="button"
                  tabIndex={0}
                  aria-expanded={llmManualOpen}
                  aria-label={
                    llmManualOpen
                      ? "Свернуть инструкцию по заполнению формы LLM"
                      : "Развернуть инструкцию по заполнению формы LLM"
                  }
                  onClick={() => setLlmManualOpen((o) => !o)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setLlmManualOpen((o) => !o);
                    }
                  }}
                  className={cn(
                    "rounded-md border border-border bg-muted/40 px-3 py-2 text-left",
                    "cursor-pointer outline-none transition-colors hover:bg-muted/60",
                    "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                    !llmManualOpen && "select-none",
                  )}
                >
                  <p className="text-sm font-medium text-foreground">
                    Как заполнить форму для разных провайдеров (Ollama, ChatGPT,
                    DeepSeek, GigaChat)
                  </p>
                  {llmManualOpen ? (
                    <div className="mt-3 space-y-2 border-t border-border pt-3 text-muted-foreground select-text">
                      <p>
                        <span className="font-medium text-foreground">
                          Как заполнить форму?
                        </span>
                      </p>
                      <p>
                        <span className="font-medium text-foreground">
                          Ollama (локально)
                        </span>{" "}
                        — укажите адрес вида{" "}
                        <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
                          http://&lt;хост&gt;:11434/api/generate
                        </code>{" "}
                        или{" "}
                        <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
                          …/api/chat
                        </code>
                        , в поле «Основная модель» — имя модели в Ollama; для
                        ключа часто достаточно значения по умолчанию или
                        произвольной строки, если сервер не требует авторизации.
                      </p>
                      <p>
                        <span className="font-medium text-foreground">
                          ChatGPT и другие сервисы в формате OpenAI
                        </span>{" "}
                        — выберите «Совместимый с OpenAI API», в URL укажите
                        конечную точку чата, например{" "}
                        <code className="break-all rounded bg-muted px-1 py-0.5 font-mono text-xs">
                          https://api.openai.com/v1/chat/completions
                        </code>
                        , в «API-ключ» — секретный ключ провайдера, в полях
                        моделей — точные идентификаторы моделей у провайдера.
                      </p>
                      <p>
                        <span className="font-medium text-foreground">
                          DeepSeek
                        </span>{" "}
                        — тот же режим «Совместимый с OpenAI API»: URL обычно{" "}
                        <code className="break-all rounded bg-muted px-1 py-0.5 font-mono text-xs">
                          https://api.deepseek.com/v1/chat/completions
                        </code>
                        , ключ — из личного кабинета DeepSeek, модель — как в
                        документации DeepSeek (например,{" "}
                        <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
                          deepseek-chat
                        </code>
                        ).
                      </p>
                      <p>
                        <span className="font-medium text-foreground">
                          GigaChat
                        </span>{" "}
                        — выберите провайдера GigaChat; адрес можно не заполнять
                        (будет адрес по умолчанию). Укажите Client ID и Client
                        secret, при необходимости Scope; в полях моделей — имена
                        моделей GigaChat. Для{" "}
                        <span className="font-medium text-foreground">
                          YandexGPT
                        </span>{" "}
                        — отдельный провайдер: API-ключ и идентификатор каталога
                        (folder_id); URL при пустом значении подставляется по
                        умолчанию.
                      </p>
                      <p>
                        После сохранения проверьте работу кнопкой «Проверить
                        соединение».
                      </p>
                    </div>
                  ) : null}
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <SettingsNotice msg={llmMsg} err={llmErr} />
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="llm-provider">Провайдер</Label>
                  <select
                    id="llm-provider"
                    className={llmSelectClass}
                    value={llmProvider}
                    onChange={(e) =>
                      setLlmProvider(e.target.value as LLMProvider)
                    }
                  >
                    <option value="ollama">Ollama (локально)</option>
                    <option value="openai_compatible">
                      Совместимый с OpenAI API
                    </option>
                    <option value="yandex_gpt">YandexGPT</option>
                    <option value="gigachat">GigaChat</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="llm-endpoint">Адрес API (URL)</Label>
                  <Input
                    id="llm-endpoint"
                    value={llmEndpoint}
                    onChange={(e) => setLlmEndpoint(e.target.value)}
                    placeholder="например, http://localhost:11434/api/chat"
                    autoComplete="off"
                  />
                </div>
              </div>
              <p className="text-xs text-muted-foreground">
                Для YandexGPT и GigaChat адрес можно оставить пустым — будет
                использован адрес по умолчанию для выбранного провайдера.
              </p>
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="llm-model">Основная модель</Label>
                  <Input
                    id="llm-model"
                    value={llmModel}
                    onChange={(e) => setLlmModel(e.target.value)}
                    placeholder="llama3.2"
                    autoComplete="off"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="llm-fast">Быстрая модель (предоценка)</Label>
                  <Input
                    id="llm-fast"
                    value={llmFastModel}
                    onChange={(e) => setLlmFastModel(e.target.value)}
                    placeholder="пусто = та же, что основная"
                    autoComplete="off"
                  />
                </div>
              </div>

              <div className="space-y-4">
                {(llmProvider === "ollama" ||
                  llmProvider === "openai_compatible" ||
                  llmProvider === "yandex_gpt") && (
                  <div className="space-y-2">
                    <Label htmlFor="llm-api-key">API-ключ / токен</Label>
                    <Input
                      id="llm-api-key"
                      type="password"
                      value={llmApiKey}
                      onChange={(e) => setLlmApiKey(e.target.value)}
                      placeholder="Оставьте пустым, чтобы не менять сохранённый ключ"
                      autoComplete="off"
                    />
                  </div>
                )}
                {llmProvider === "yandex_gpt" && (
                  <div className="space-y-2">
                    <Label htmlFor="llm-folder">
                      Идентификатор каталога (folder_id)
                    </Label>
                    <Input
                      id="llm-folder"
                      value={llmFolderId}
                      onChange={(e) => setLlmFolderId(e.target.value)}
                      autoComplete="off"
                    />
                  </div>
                )}
                {llmProvider === "gigachat" && (
                  <div className="space-y-4">
                    <div className="space-y-2">
                      <Label htmlFor="llm-giga-client">Client ID</Label>
                      <Input
                        id="llm-giga-client"
                        value={llmClientId}
                        onChange={(e) => setLlmClientId(e.target.value)}
                        autoComplete="off"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="llm-giga-secret">Client secret</Label>
                      <Input
                        id="llm-giga-secret"
                        type="password"
                        value={llmClientSecret}
                        onChange={(e) => setLlmClientSecret(e.target.value)}
                        placeholder="Оставьте пустым, чтобы не менять сохранённый секрет"
                        autoComplete="off"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="llm-giga-scope">
                        Scope (необязательно)
                      </Label>
                      <Input
                        id="llm-giga-scope"
                        value={llmScope}
                        onChange={(e) => setLlmScope(e.target.value)}
                        placeholder="GIGACHAT_API_PERS"
                        autoComplete="off"
                      />
                    </div>
                  </div>
                )}
              </div>

              {llmTestHint && (
                <p className="text-sm text-muted-foreground">{llmTestHint}</p>
              )}
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  onClick={() => void saveLlmSettings()}
                  disabled={savingLlm || !llmModel.trim()}
                >
                  {savingLlm ? "Сохранение…" : "Сохранить настройки LLM"}
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => void runLlmTest()}
                  disabled={testingLlm}
                >
                  {testingLlm ? "Проверка…" : "Проверить соединение"}
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Настройки e-staff</CardTitle>
              <CardDescription>
                Домен (имя сервера до «.e-staff.ru») и API-токен из панели
                e-staff. Статус:{" "}
                {estaffConfigured ? "настроено" : "не настроено"}. Токен после
                сохранения не отображается.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <SettingsNotice msg={estaffMsg} err={estaffErr} />
              <div className="space-y-2">
                <Label htmlFor="estaff-server">Домен (server name)</Label>
                <Input
                  id="estaff-server"
                  value={estaffServer}
                  onChange={(e) => setEstaffServer(e.target.value)}
                  placeholder="например, mycompany"
                  autoComplete="off"
                />
                <p className="text-xs text-muted-foreground">
                  Короткое имя (например krit) даст https://krit.e-staff.ru; можно
                  указать полный хост с точкой или URL со схемой. Пути к API задаёт
                  backend.
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="estaff-token">API-токен</Label>
                <Input
                  id="estaff-token"
                  type="password"
                  value={estaffToken}
                  onChange={(e) => setEstaffToken(e.target.value)}
                  placeholder="Вставьте токен из e-staff"
                  autoComplete="off"
                />
                <p className="text-xs text-muted-foreground">
                  Зайдите в раздел «Администрирование». На вкладке «Доступ к API»
                  создайте API-токен или выберите существующий. Скопируйте
                  полученный API-токен в это поле.
                </p>
              </div>
              <Button
                type="button"
                onClick={() => void saveEstaffCredentials()}
                disabled={
                  savingEstaff || !estaffServer.trim() || !estaffToken.trim()
                }
              >
                {savingEstaff ? "Сохранение…" : "Сохранить настройки e-staff"}
              </Button>
            </CardContent>
          </Card>

        </div>
        ) : null}

        <Card>
          <CardHeader>
            <CardTitle>HeadHunter</CardTitle>
            <CardDescription>
              Подключение аккаунта для поиска резюме (OAuth). При включённом
              mock HH доступен мгновенный тестовый callback.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <SettingsNotice msg={hhMsg} err={hhErr} />
            <Button onClick={startConnect} disabled={busy}>
              {busy ? "Подождите…" : "Подключить HeadHunter"}
            </Button>
          </CardContent>
        </Card>

        <div className="mt-12 flex justify-center">
          <Link href="/search" className="text-sm text-muted-foreground hover:text-primary transition-colors">
            Вернуться к поиску
          </Link>
        </div>
      </main>
    </>
  );
}

export default function SettingsPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center">
          <p className="text-muted-foreground">Загрузка…</p>
        </main>
      }
    >
      <SettingsBody />
    </Suspense>
  );
}
