"use client";

import type { ParsedParams } from "@/lib/types";
import { cn } from "@/lib/utils";

const LABELS: Record<string, string> = {
  skills: "Навыки",
  experience_years_min: "Мин. лет",
  region: "Регион",
  position_keywords: "Роль",
  gender: "Пол",
  industry: "Отрасль",
  age_max: "Макс. возраст",
};

function formatValue(key: string, v: unknown): string {
  if (v == null) return "";
  if (Array.isArray(v)) return v.map(String).join(", ");
  return String(v);
}

type Props = {
  params: ParsedParams | null;
  confidence?: number | null;
  className?: string;
};

export function ParsedTags({ params, confidence, className }: Props) {
  if (!params || Object.keys(params).length === 0) {
    return (
      <p className={cn("text-sm text-muted-foreground", className)}>
        Распознанные параметры появятся после выполнения поиска.
      </p>
    );
  }

  const entries = Object.entries(params).filter(
    ([, v]) => v != null && v !== "" && !(Array.isArray(v) && v.length === 0),
  );

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex flex-wrap gap-2">
        {entries.map(([key, v]) => (
          <span
            key={key}
            className="inline-flex items-center rounded-full border bg-muted/50 px-3 py-1 text-xs"
          >
            <span className="text-muted-foreground">
              {LABELS[key] ?? key}:{" "}
            </span>
            <span className="ml-1 font-medium">{formatValue(key, v)}</span>
          </span>
        ))}
      </div>
      {confidence != null && (
        <p className="text-xs text-muted-foreground">
          Достоверность: {(confidence * 100).toFixed(0)}%
        </p>
      )}
    </div>
  );
}
