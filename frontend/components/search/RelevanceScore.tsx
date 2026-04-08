"use client";

import { RelevanceBar } from "@/components/search/RelevanceBar";
import { cn } from "@/lib/utils";

/** Локальный тип для устаревшего блока «системная релевантность» (не используется в текущем API). */
export type RelevanceBreakdown = {
  overall_score: number;
  skills_match: number | null;
  experience_match: number | null;
  industry_match: number | null;
  position_match: number | null;
  location_match: number | null;
  recommendation: string;
  summary: string;
};

type Props = {
  relevance: RelevanceBreakdown;
  compact?: boolean;
  className?: string;
};

export function RelevanceScore({ relevance, compact, className }: Props) {
  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-medium">Релевантность</span>
        <span className="text-lg font-semibold tabular-nums">
          {relevance.overall_score}
        </span>
      </div>
      <RelevanceBar value={relevance.overall_score} />
      {!compact && (
        <ul className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <li>
            Навыки:{" "}
            {relevance.skills_match != null ? relevance.skills_match : "—"}
          </li>
          <li>
            Опыт:{" "}
            {relevance.experience_match != null
              ? relevance.experience_match
              : "—"}
          </li>
          <li>
            Регион:{" "}
            {relevance.location_match != null
              ? relevance.location_match
              : "—"}
          </li>
          <li>
            Роль:{" "}
            {relevance.position_match != null
              ? relevance.position_match
              : "—"}
          </li>
        </ul>
      )}
    </div>
  );
}
