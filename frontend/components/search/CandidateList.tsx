"use client";

import { Search } from "lucide-react";

import { CandidateCard } from "@/components/search/CandidateCard";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import type { EstaffExportLatestResponse } from "@/lib/api";
import type { Candidate } from "@/lib/types";

type Props = {
  items: Candidate[];
  searchQuery?: string;
  favoriteByResumeId?: Record<string, string>;
  favoriteBusyResumeId?: string | null;
  onToggleFavorite?: (candidate: Candidate) => void;
  onAnalyze?: (candidate: Candidate) => void;
  analyzeBusyResumeId?: string | null;
  analyzeDisabled?: boolean;
  /** После поиска с нулём совпадений — расширенные подсказки */
  showEmptyGuidance?: boolean;
  loading?: boolean;
  estaffLatestByResumeId?: Record<string, EstaffExportLatestResponse>;
  onEstaffExportUpdated?: () => void;
};

function CandidateCardSkeleton() {
  return (
    <Card className="flex h-full min-h-0 flex-col">
      <CardHeader className="pb-2">
        <Skeleton className="h-5 w-3/4 max-w-xs" />
        <Skeleton className="mt-2 h-4 w-1/2 max-w-[200px]" />
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
        <Skeleton className="h-8 w-full max-w-[220px]" />
        <Skeleton className="h-32 w-full shrink-0 rounded-md" />
      </CardContent>
    </Card>
  );
}

export function CandidateList({
  items,
  searchQuery,
  favoriteByResumeId,
  favoriteBusyResumeId,
  onToggleFavorite,
  onAnalyze,
  analyzeBusyResumeId,
  analyzeDisabled,
  showEmptyGuidance,
  loading,
  estaffLatestByResumeId,
  onEstaffExportUpdated,
}: Props) {
  if (loading) {
    return (
      <ul className="grid gap-4 md:grid-cols-2" aria-busy="true" aria-label="Загрузка кандидатов">
        {Array.from({ length: 4 }, (_, i) => (
          <li key={i} className="h-full min-h-0">
            <CandidateCardSkeleton />
          </li>
        ))}
      </ul>
    );
  }

  if (items.length === 0) {
    if (showEmptyGuidance) {
      return (
        <EmptyState
          icon={<Search className="h-8 w-8" />}
          title="Никого не нашли"
          description="По заданным критериям кандидаты не найдены. Попробуйте следующее:"
        >
          <ul className="mt-4 space-y-2 text-left text-sm text-muted-foreground">
            <li className="flex items-start gap-2">
              <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
              <span>Смягчите формулировку запроса или уберите узкие требования</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
              <span>Ослабьте или сбросьте фильтры: регион, опыт, зарплата</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
              <span>Расширьте регион поиска</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
              <span>Попробуйте синонимы должности</span>
            </li>
          </ul>
        </EmptyState>
      );
    }
    return (
      <EmptyState
        icon={<Search className="h-8 w-8" />}
        title="Кандидаты не найдены"
        description="Попробуйте изменить запрос или фильтры поиска"
      />
    );
  }

  return (
    <ul className="grid gap-4 md:grid-cols-2">
      {items.map((c) => {
        const resumeKey = (c.hh_resume_id || c.id).trim();
        return (
        <li key={resumeKey} className="h-full min-h-0">
          <CandidateCard
            candidate={c}
            searchQuery={searchQuery}
            favoriteId={favoriteByResumeId?.[resumeKey]}
            favoriteBusy={favoriteBusyResumeId === resumeKey}
            onToggleFavorite={onToggleFavorite}
            onAnalyze={onAnalyze}
            analyzeBusy={
              analyzeBusyResumeId != null &&
              analyzeBusyResumeId === (c.hh_resume_id || c.id)
            }
            analyzeDisabled={Boolean(analyzeDisabled)}
            estaffLatestByResumeId={estaffLatestByResumeId}
            onEstaffExportUpdated={onEstaffExportUpdated}
          />
        </li>
      );
      })}
    </ul>
  );
}
