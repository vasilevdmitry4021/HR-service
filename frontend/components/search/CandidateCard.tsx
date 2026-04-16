"use client";

import Link from "next/link";
import { Loader2 } from "lucide-react";

import { ExportToEStaffButton } from "@/components/ExportToEStaffButton";
import { FavoriteHeartButton } from "@/components/FavoriteHeartButton";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { EstaffExportLatestResponse } from "@/lib/api";
import { formatResumeSalaryExpectations } from "@/lib/salary-format";
import { cn } from "@/lib/utils";
import type { Candidate } from "@/lib/types";

import { HhResumeLinkButton } from "./HhResumeLinkButton";

type Props = {
  candidate: Candidate;
  searchQuery?: string;
  favoriteId?: string | null;
  favoriteBusy?: boolean;
  onToggleFavorite?: (candidate: Candidate) => void;
  onAnalyze?: (candidate: Candidate) => void;
  analyzeBusy?: boolean;
  analyzeDisabled?: boolean;
  estaffLatestByResumeId?: Record<string, EstaffExportLatestResponse>;
  onEstaffExportUpdated?: () => void;
};

export function CandidateCard({
  candidate,
  searchQuery,
  favoriteId,
  favoriteBusy,
  onToggleFavorite,
  onAnalyze,
  analyzeBusy,
  analyzeDisabled,
  estaffLatestByResumeId,
  onEstaffExportUpdated,
}: Props) {
  const salaryText = formatResumeSalaryExpectations(candidate.salary);
  const salarySpecified = salaryText !== "Не указана";
  const rid = candidate.hh_resume_id || candidate.id;
  const detailHref =
    searchQuery && searchQuery.trim()
      ? `/candidates/${encodeURIComponent(rid)}?q=${encodeURIComponent(searchQuery.trim())}`
      : `/candidates/${encodeURIComponent(rid)}`;
  const inFav = Boolean(favoriteId);
  const analysis = candidate.llm_analysis;
  const hasDetailed = analysis != null;
  const prescore = candidate.llm_score;
  const scoreLabel = hasDetailed ? analysis.llm_score : prescore;
  const summaryTrimmed = hasDetailed ? analysis.summary?.trim() : null;
  const summaryText = summaryTrimmed
    ? summaryTrimmed
    : hasDetailed
      ? "Краткая оценка недоступна. Откройте карточку кандидата для подробностей."
      : prescore != null
        ? `Предварительная оценка соответствия запросу: ${prescore} баллов. Для развёрнутого разбора воспользуйтесь кнопкой «Детальный анализ» над списком или оцените это резюме отдельно.`
        : "Оценка ещё не выполнена. Нажмите «Оценить выдачу» над списком результатов или запросите оценку для этого резюме.";
  const canRequestAi =
    Boolean(onAnalyze) &&
    !hasDetailed &&
    Boolean(searchQuery?.trim());

  return (
    <Card className="flex h-full min-h-0 flex-col shadow-base transition-shadow hover:shadow-float">
      <CardHeader className="pb-2">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <CardTitle className="text-lg">
              <Link
                href={detailHref}
                className="hover:text-primary hover:underline"
              >
                {candidate.title || "Без названия"}
              </Link>
              {candidate.source_type === "telegram" ? (
                <span className="ml-2 align-middle text-xs font-normal text-muted-foreground">
                  (Telegram)
                </span>
              ) : null}
            </CardTitle>
            <p className="text-sm text-muted-foreground">
              {[candidate.full_name, candidate.area].filter(Boolean).join(" · ")}
            </p>
          </div>
          {onToggleFavorite && (
            <FavoriteHeartButton
              inFavorites={inFav}
              busy={favoriteBusy}
              onClick={() => onToggleFavorite(candidate)}
            />
          )}
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-4">
        {(candidate.experience_years != null || candidate.age != null) && (
          <p className="text-xs text-muted-foreground">
            {candidate.experience_years != null &&
              `Опыт: ${candidate.experience_years} лет`}
            {candidate.experience_years != null && candidate.age != null && " · "}
            {candidate.age != null && `Возраст: ${candidate.age}`}
          </p>
        )}
        <p className="text-sm">
          <span className="text-muted-foreground">Зарплата: </span>
          <span
            className={
              salarySpecified ? "font-medium" : "font-medium text-muted-foreground"
            }
          >
            {salaryText}
          </span>
        </p>
        <div
          className={cn(
            "flex shrink-0 flex-col rounded-md bg-muted/50 p-2 text-sm",
            hasDetailed && "motion-safe:transition-opacity motion-safe:duration-500",
          )}
          aria-label={hasDetailed ? "Детальная оценка ИИ" : "Оценка по выдаче"}
        >
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 gap-y-1">
              <span className="font-medium">
                {hasDetailed ? "Детальная оценка ИИ" : "Оценка по выдаче"}
              </span>
              {scoreLabel != null && (
                <span
                  className={cn(
                    "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold",
                    scoreLabel >= 80
                      ? "bg-[hsl(133_84%_37%)] text-white"
                      : scoreLabel >= 60
                        ? "bg-[hsl(38_98%_48%)] text-white"
                        : "bg-muted text-muted-foreground",
                  )}
                >
                  {scoreLabel}
                </span>
              )}
            </div>
            {canRequestAi && (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                className="shrink-0 gap-1.5"
                disabled={analyzeBusy || analyzeDisabled || !searchQuery?.trim()}
                onClick={() => onAnalyze?.(candidate)}
              >
                {analyzeBusy ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />
                    Оценка…
                  </>
                ) : (
                  "Оценить ИИ"
                )}
              </Button>
            )}
          </div>
          <div className="mt-1 overflow-hidden">
            <p
              className={`line-clamp-4 text-sm leading-snug [overflow-wrap:anywhere] ${
                summaryTrimmed ? "text-foreground" : "text-muted-foreground"
              }`}
            >
              {summaryText}
            </p>
          </div>
        </div>
        <div className="mt-auto flex flex-wrap items-start gap-2">
          <ExportToEStaffButton
            hhResumeId={rid}
            parentEstaffLatest={
              estaffLatestByResumeId !== undefined
                ? (estaffLatestByResumeId[rid] ?? null)
                : undefined
            }
            onEstaffStatusUpdated={onEstaffExportUpdated}
            hrLlmSummary={analysis?.summary ?? null}
            hrLlmScore={analysis?.llm_score ?? prescore ?? null}
            hrLlmAnalysis={analysis ?? null}
            hrSearchQuery={searchQuery?.trim() || null}
          />
          <HhResumeLinkButton
            url={candidate.hh_resume_url}
            label={
              candidate.source_type === "telegram"
                ? "Сообщение в Telegram"
                : undefined
            }
          />
        </div>
      </CardContent>
    </Card>
  );
}
