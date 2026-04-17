"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { AppNav } from "@/components/AppNav";
import { ExportToEStaffButton } from "@/components/ExportToEStaffButton";
import { FavoriteHeartButton } from "@/components/FavoriteHeartButton";
import { LlmModelAssessmentCard } from "@/components/LlmModelAssessmentCard";
import { HhResumeLinkButton } from "@/components/search/HhResumeLinkButton";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  addFavorite,
  analyzeCandidate,
  ApiError,
  downloadCandidatePdfBlob,
  fetchCandidateDetail,
  removeFavorite,
} from "@/lib/api";
import { formatResumeSalaryExpectations } from "@/lib/salary-format";
import type { CandidateDetail, LLMAnalysis } from "@/lib/types";
import { useAuthStore } from "@/stores/auth-store";

const pdfExportEnabled =
  typeof process !== "undefined" &&
  process.env.NEXT_PUBLIC_FEATURE_PDF_EXPORT === "true";

function DetailSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="Загрузка">
      <Skeleton className="h-8 w-2/3 max-w-md" />
      <Skeleton className="h-4 w-48" />
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-32" />
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-40" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    </div>
  );
}

function CandidateDetailInner({
  params,
}: {
  params: { id: string };
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const accessToken = useAuthStore((s) => s.accessToken);
  const hasHydrated = useAuthStore((s) => s._hasHydrated);
  const resumeId = decodeURIComponent(params.id);
  const q = searchParams.get("q") ?? "";

  const [data, setData] = useState<CandidateDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [favBusy, setFavBusy] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [analyzeBusy, setAnalyzeBusy] = useState(false);
  const [llmAnalysis, setLlmAnalysis] = useState<LLMAnalysis | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const row = await fetchCandidateDetail(resumeId, q || undefined);
      setData(row);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось загрузить");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [resumeId, q]);

  useEffect(() => {
    if (!hasHydrated) return;
    if (!accessToken) {
      router.replace("/login");
      return;
    }
    void load();
  }, [hasHydrated, accessToken, load, router]);

  useEffect(() => {
    setLlmAnalysis(data?.llm_analysis ?? null);
  }, [data]);

  const runAnalyze = async () => {
    if (!q.trim()) {
      setError("Для оценки резюме необходим поисковый запрос");
      return;
    }
    setAnalyzeBusy(true);
    setError(null);
    try {
      const result = await analyzeCandidate(resumeId, q);
      setLlmAnalysis(result);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось получить оценку");
    } finally {
      setAnalyzeBusy(false);
    }
  };

  const downloadPdf = async () => {
    if (!pdfExportEnabled) return;
    setPdfBusy(true);
    setError(null);
    try {
      const blob = await downloadCandidatePdfBlob(resumeId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `resume_${resumeId.replace(/[^\w.-]+/g, "_")}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось скачать PDF");
    } finally {
      setPdfBusy(false);
    }
  };

  const toggleFavorite = async () => {
    if (!data) return;
    setFavBusy(true);
    setError(null);
    try {
      if (data.favorite_id) {
        await removeFavorite(data.favorite_id);
      } else {
        await addFavorite({
          ...data,
          llm_analysis: llmAnalysis ?? data.llm_analysis ?? null,
        });
      }
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Ошибка избранного");
    } finally {
      setFavBusy(false);
    }
  };

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

  const salaryLine =
    data != null ? formatResumeSalaryExpectations(data.salary) : "Не указана";
  const salarySpecified = salaryLine !== "Не указана";

  return (
    <>
      <AppNav />
      <main className="mx-auto max-w-3xl space-y-6 px-4 py-8">
        <div className="flex flex-wrap items-center gap-3">
          <Link
            href="/search"
            className="text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground"
          >
            ← К поиску
          </Link>
          {q ? (
            <span className="text-xs text-muted-foreground">
              Оценка по запросу: «{q.length > 60 ? `${q.slice(0, 60)}…` : q}»
            </span>
          ) : null}
        </div>

        {error && (
          <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        )}

        {loading && <DetailSkeleton />}

        {!loading && data && (
          <>
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0 flex-1">
                <h1 className="text-2xl font-semibold tracking-tight">
                  {data.title || "Резюме"}
                </h1>
                <p className="mt-1 text-muted-foreground">
                  {[data.full_name, data.area].filter(Boolean).join(" · ")}
                </p>
              </div>
              <div className="flex w-full shrink-0 flex-col gap-2 sm:w-auto sm:max-w-none sm:flex-row sm:flex-wrap sm:justify-end">
                <ExportToEStaffButton
                  hhResumeId={data.hh_resume_id || resumeId}
                  size="default"
                  className="w-full sm:w-auto"
                  hrLlmSummary={llmAnalysis?.summary ?? null}
                  hrLlmScore={llmAnalysis?.llm_score ?? null}
                  hrLlmAnalysis={llmAnalysis}
                  hrSearchQuery={q.trim() || null}
                />
                <HhResumeLinkButton
                  url={data.hh_resume_url}
                  size="default"
                  className="w-full sm:w-auto"
                />
                {pdfExportEnabled && (
                  <Button
                    type="button"
                    variant="outline"
                    className="w-full sm:w-auto"
                    disabled={pdfBusy}
                    onClick={() => void downloadPdf()}
                  >
                    {pdfBusy ? "PDF…" : "Скачать PDF"}
                  </Button>
                )}
                <FavoriteHeartButton
                  inFavorites={Boolean(data.favorite_id)}
                  busy={favBusy}
                  onClick={() => void toggleFavorite()}
                />
              </div>
            </div>

            {llmAnalysis ? (
              <LlmModelAssessmentCard analysis={llmAnalysis} />
            ) : q.trim() ? (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Оценка модели</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="mb-3 text-sm text-muted-foreground">
                    Оценка ИИ ещё не проводилась для этого резюме.
                  </p>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={analyzeBusy}
                    onClick={() => void runAnalyze()}
                  >
                    {analyzeBusy ? "Анализ..." : "Оценить с помощью ИИ"}
                  </Button>
                </CardContent>
              </Card>
            ) : null}

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Сводка</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                {data.skills.length > 0 && (
                  <p>
                    <span className="text-muted-foreground">Навыки: </span>
                    {data.skills.join(", ")}
                  </p>
                )}
                <p className="text-muted-foreground">
                  {data.experience_years != null && (
                    <>Опыт: {data.experience_years} лет </>
                  )}
                  {data.age != null && <>· Возраст: {data.age}</>}
                </p>
                <p>
                  <span className="text-muted-foreground">
                    Зарплата:{" "}
                  </span>
                  <span
                    className={
                      salarySpecified
                        ? "font-medium"
                        : "font-medium text-muted-foreground"
                    }
                  >
                    {salaryLine}
                  </span>
                </p>
              </CardContent>
            </Card>

            {data.about?.trim() ? (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">О себе</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
                    {data.about.trim()}
                  </p>
                </CardContent>
              </Card>
            ) : null}

            {data.work_experience && data.work_experience.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Опыт работы</CardTitle>
                </CardHeader>
                <CardContent className="space-y-6 text-sm">
                  {data.work_experience.map((job, idx) => (
                    <div
                      key={`${job.company}-${job.position}-${idx}`}
                      className="border-b border-border pb-6 last:border-b-0 last:pb-0"
                    >
                      <div className="flex flex-col gap-1 sm:flex-row sm:flex-wrap sm:items-baseline sm:justify-between">
                        <p className="font-medium text-foreground">
                          {job.position || "Должность не указана"}
                        </p>
                        {job.period_label ? (
                          <p className="shrink-0 text-xs text-muted-foreground tabular-nums">
                            {job.period_label}
                          </p>
                        ) : null}
                      </div>
                      {job.company ? (
                        <p className="mt-1 text-muted-foreground">{job.company}</p>
                      ) : null}
                      <p className="mt-1 text-xs text-muted-foreground">
                        {[job.area, job.industry].filter(Boolean).join(" · ")}
                      </p>
                      {job.description ? (
                        <p className="mt-3 whitespace-pre-wrap leading-relaxed text-foreground">
                          {job.description}
                        </p>
                      ) : null}
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}

            {data.education && data.education.length > 0 ? (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Образование</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3 text-sm">
                  {data.education.map((ed, idx) => (
                    <p
                      key={`${ed.summary ?? ed.organization ?? ""}-${idx}`}
                      className="leading-relaxed text-foreground"
                    >
                      {ed.summary ||
                        [ed.level, ed.organization, ed.speciality, ed.year]
                          .filter(Boolean)
                          .join(" · ")}
                    </p>
                  ))}
                </CardContent>
              </Card>
            ) : null}

            {data.favorite_id && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Заметка в избранном</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="whitespace-pre-wrap text-sm text-muted-foreground">
                    {data.favorite_notes ||
                      "Заметок пока нет — добавьте на странице «Избранное»."}
                  </p>
                  <Link
                    href="/favorites"
                    className="mt-3 inline-block text-sm text-primary underline"
                  >
                    Редактировать в избранном
                  </Link>
                </CardContent>
              </Card>
            )}
          </>
        )}
      </main>
    </>
  );
}

export default function CandidateDetailPage(props: { params: { id: string } }) {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center p-4">
          <p className="text-muted-foreground">Загрузка…</p>
        </main>
      }
    >
      <CandidateDetailInner {...props} />
    </Suspense>
  );
}
