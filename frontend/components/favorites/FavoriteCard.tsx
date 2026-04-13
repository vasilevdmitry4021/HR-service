"use client";

import Link from "next/link";
import { useState } from "react";

import { ExportToEStaffButton } from "@/components/ExportToEStaffButton";
import { LlmModelAssessmentCard } from "@/components/LlmModelAssessmentCard";
import {
  ApiError,
  postFavoriteRefreshFromHh,
  type EstaffExportLatestResponse,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatFavoriteSalaryAmount } from "@/lib/salary-format";
import { cn } from "@/lib/utils";
import type { FavoriteRow } from "@/lib/types";

type Props = {
  favorite: FavoriteRow;
  draftNotes: string;
  onNotesChange: (value: string) => void;
  onSaveNotes: () => void;
  onRemove: () => void;
  savingNotes: boolean;
  notesSaved: boolean;
  selectionMode?: boolean;
  selected?: boolean;
  onSelectionChange?: (selected: boolean) => void;
  parentEstaffLatest?: EstaffExportLatestResponse | null;
  onEstaffExportUpdated?: () => void;
  onFavoriteRefreshed?: (row: FavoriteRow) => void;
};

export function FavoriteCard({
  favorite,
  draftNotes,
  onNotesChange,
  onSaveNotes,
  onRemove,
  savingNotes,
  notesSaved,
  selectionMode,
  selected,
  onSelectionChange,
  parentEstaffLatest,
  onEstaffExportUpdated,
  onFavoriteRefreshed,
}: Props) {
  const [refreshingHh, setRefreshingHh] = useState(false);
  const [refreshHhError, setRefreshHhError] = useState<string | null>(null);
  const [contactsHint, setContactsHint] = useState<string | null>(null);

  const skills = favorite.skills_snapshot;
  const skillsText =
    Array.isArray(skills) && skills.length > 0
      ? skills.join(", ")
      : null;
  const resumeKey = (
    favorite.hh_resume_id?.trim() ||
    favorite.candidate_id ||
    ""
  ).trim();
  const detailHref = `/candidates/${encodeURIComponent(resumeKey || "unknown")}`;
  const title =
    favorite.title_snapshot || favorite.hh_resume_id || favorite.candidate_id || "Кандидат";
  const favSalaryText = formatFavoriteSalaryAmount(
    favorite.salary_amount,
    favorite.salary_currency,
  );
  const favSalaryOk = favSalaryText !== "Не указана";
  const canRefreshFromHh = Boolean(favorite.hh_resume_id?.trim());

  const storedAnalysis = favorite.llm_analysis;
  const hasStoredFullAnalysis =
    storedAnalysis != null &&
    (storedAnalysis.llm_score != null ||
      storedAnalysis.is_relevant != null ||
      (storedAnalysis.strengths?.length ?? 0) > 0 ||
      (storedAnalysis.gaps?.length ?? 0) > 0 ||
      Boolean(storedAnalysis.summary?.trim()));

  const handleRefreshFromHh = async () => {
    if (!canRefreshFromHh) return;
    setRefreshingHh(true);
    setRefreshHhError(null);
    try {
      const data = await postFavoriteRefreshFromHh(favorite.id);
      onFavoriteRefreshed?.(data.favorite);
      if (!data.meta.contacts_unlocked && data.meta.message) {
        setContactsHint(data.meta.message);
      } else {
        setContactsHint(null);
      }
    } catch (e) {
      setContactsHint(null);
      setRefreshHhError(
        e instanceof ApiError ? e.message : "Не удалось обновить с HeadHunter",
      );
    } finally {
      setRefreshingHh(false);
    }
  };

  return (
    <Card className="shadow-base transition-shadow hover:shadow-float">
      <CardHeader className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          {selectionMode ? (
            <label className="mb-2 flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4 shrink-0 rounded border border-input accent-primary"
                checked={Boolean(selected)}
                onChange={(e) => onSelectionChange?.(e.target.checked)}
              />
              <span className="text-muted-foreground">Выбрать для выгрузки</span>
            </label>
          ) : null}
          <CardTitle className="text-lg">
            <Link
              href={detailHref}
              className="hover:text-primary hover:underline"
            >
              {title}
            </Link>
          </CardTitle>
          {(favorite.full_name || favorite.area) && (
            <p className="text-sm text-muted-foreground">
              {[favorite.full_name, favorite.area].filter(Boolean).join(" · ")}
            </p>
          )}
          {(favorite.contact_email || favorite.contact_phone) && (
            <p className="text-sm text-muted-foreground">
              {[
                favorite.contact_email,
                favorite.contact_phone,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          )}
          {contactsHint ? (
            <p className="text-xs text-muted-foreground">{contactsHint}</p>
          ) : null}
          {refreshHhError ? (
            <p className="text-xs text-destructive">{refreshHhError}</p>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-col gap-2 sm:flex-row sm:items-start">
          <ExportToEStaffButton
            hhResumeId={resumeKey}
            parentEstaffLatest={parentEstaffLatest}
            onEstaffStatusUpdated={onEstaffExportUpdated}
            showToastNotifications={false}
            hrLlmSummary={
              favorite.llm_analysis?.summary ?? favorite.llm_summary
            }
            hrLlmScore={
              favorite.llm_analysis?.llm_score ?? favorite.llm_score
            }
            hrLlmAnalysis={favorite.llm_analysis ?? null}
          />
          <Link href={detailHref}>
            <Button type="button" variant="outline" size="sm">
              Подробнее
            </Button>
          </Link>
          {canRefreshFromHh ? (
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={refreshingHh}
              onClick={() => void handleRefreshFromHh()}
            >
              {refreshingHh ? "Обновление…" : "Обновить с HH"}
            </Button>
          ) : null}
          <Button
            type="button"
            variant="destructive"
            size="sm"
            onClick={onRemove}
          >
            Удалить
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {skillsText && (
          <p className="text-sm">
            <span className="text-muted-foreground">Навыки: </span>
            {skillsText}
          </p>
        )}
        {(favorite.experience_years != null || favorite.age != null) && (
          <p className="text-xs text-muted-foreground">
            {favorite.experience_years != null &&
              `Опыт: ${favorite.experience_years} лет`}
            {favorite.experience_years != null && favorite.age != null && " · "}
            {favorite.age != null && `Возраст: ${favorite.age}`}
          </p>
        )}
        <p className="text-sm">
          <span className="text-muted-foreground">Зарплата: </span>
          <span
            className={
              favSalaryOk ? "font-medium" : "font-medium text-muted-foreground"
            }
          >
            {favSalaryText}
          </span>
        </p>
        {hasStoredFullAnalysis ? (
          <LlmModelAssessmentCard analysis={storedAnalysis} />
        ) : (favorite.llm_score != null || favorite.llm_summary) ? (
          <div
            className="rounded-md bg-muted/50 p-2 text-sm"
            aria-label="Оценка модели"
          >
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <span className="font-medium">Оценка модели:</span>
              {favorite.llm_score != null && (
                <span
                  className={cn(
                    "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold",
                    favorite.llm_score >= 80
                      ? "bg-[hsl(133_84%_37%)] text-white"
                      : favorite.llm_score >= 60
                        ? "bg-[hsl(38_98%_48%)] text-white"
                        : "bg-muted text-muted-foreground",
                  )}
                >
                  {favorite.llm_score}
                </span>
              )}
            </div>
            {favorite.llm_summary?.trim() && (
              <p className="mt-1 text-muted-foreground">
                {favorite.llm_summary.trim()}
              </p>
            )}
          </div>
        ) : null}
        <div className="space-y-2">
          <label
            className="text-sm font-medium"
            htmlFor={`notes-${favorite.id}`}
          >
            Заметки
          </label>
          <textarea
            id={`notes-${favorite.id}`}
            rows={4}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            value={draftNotes}
            onChange={(e) => onNotesChange(e.target.value)}
          />
          <Button
            type="button"
            size="sm"
            disabled={savingNotes}
            onClick={onSaveNotes}
            className={
              notesSaved
                ? "border-green-600 bg-green-600/10 text-green-700 dark:border-green-500 dark:bg-green-500/10 dark:text-green-400"
                : ""
            }
          >
            {savingNotes
              ? "Сохранение…"
              : notesSaved
                ? "Сохранено"
                : "Сохранить заметки"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
