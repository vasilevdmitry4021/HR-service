"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { LLMAnalysis } from "@/lib/types";

type Props = {
  analysis: LLMAnalysis | null | undefined;
};

/** Блок «Оценка модели»: вывод, балл, релевантность, списки сильных сторон и пробелов */
export function LlmModelAssessmentCard({ analysis }: Props) {
  if (!analysis) return null;
  const hasText =
    Boolean(analysis.summary?.trim()) ||
    analysis.llm_score != null ||
    analysis.is_relevant != null ||
    (analysis.strengths?.length ?? 0) > 0 ||
    (analysis.gaps?.length ?? 0) > 0;
  if (!hasText) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Оценка модели</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        {analysis.summary?.trim() && (
          <p className="rounded-md bg-muted/50 p-3">
            <span className="font-medium">Вывод: </span>
            {analysis.summary.trim()}
          </p>
        )}
        {(analysis.llm_score != null || analysis.is_relevant != null) && (
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground">
            {analysis.llm_score != null && (
              <span>Балл: {analysis.llm_score}</span>
            )}
            {analysis.is_relevant != null && (
              <span>
                По мнению модели:{" "}
                {analysis.is_relevant ? "релевантен" : "не релевантен"}
              </span>
            )}
          </div>
        )}
        {(analysis.strengths?.length ?? 0) > 0 && (
          <div>
            <p className="mb-1 font-medium">Сильные стороны</p>
            <ul className="list-inside list-disc text-muted-foreground">
              {analysis.strengths!.map((s, i) => (
                <li key={`${i}-${s}`}>{s}</li>
              ))}
            </ul>
          </div>
        )}
        {(analysis.gaps?.length ?? 0) > 0 && (
          <div>
            <p className="mb-1 font-medium">Пробелы и риски</p>
            <ul className="list-inside list-disc text-muted-foreground">
              {analysis.gaps!.map((g, i) => (
                <li key={`${i}-${g}`}>{g}</li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
