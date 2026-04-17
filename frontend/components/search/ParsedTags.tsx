"use client";

import type { ParsedParams } from "@/lib/types";
import { cn } from "@/lib/utils";

const LABELS: Record<string, string> = {
  must_position: "Роль (обязательно)",
  must_skills: "Навыки (обязательно)",
  should_skills: "Навыки (желательно)",
  soft_signals: "Мягкие сигналы",
};

const SECTION_TITLES: Record<string, string> = {
  required: "Обязательные",
  optional: "Дополнительно",
};

const SECTIONS: Array<{ id: "required" | "optional"; keys: string[] }> = [
  {
    id: "required",
    keys: ["must_position", "must_skills"],
  },
  {
    id: "optional",
    keys: ["should_skills", "soft_signals"],
  },
];

type SkillGroup = {
  canonical?: unknown;
  synonyms?: unknown;
};

function isSkillGroup(value: unknown): value is SkillGroup {
  return typeof value === "object" && value != null && "canonical" in value;
}

function formatSkillGroup(value: SkillGroup): string {
  const canonical = String(value.canonical ?? "").trim();
  if (canonical) return canonical;
  const synonyms = Array.isArray(value.synonyms)
    ? value.synonyms.map((item) => String(item).trim()).filter((item) => item.length > 0)
    : [];
  return synonyms.join(", ");
}

function formatValue(key: string, v: unknown): string {
  if (v == null) return "";
  if (Array.isArray(v)) {
    if (key === "must_skills" || key === "should_skills") {
      return v
        .map((item) => (isSkillGroup(item) ? formatSkillGroup(item) : String(item)))
        .filter((item) => item.trim().length > 0)
        .join(", ");
    }
    return v
      .map((item) => String(item).trim())
      .filter((item) => item.length > 0)
      .join(", ");
  }
  if (typeof v === "object") return "";
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

  const visibleKeys = new Set(SECTIONS.flatMap((section) => section.keys));
  const entries = Object.entries(params)
    .filter(([key]) => visibleKeys.has(key))
    .map(([key, v]) => ({ key, value: formatValue(key, v) }))
    .filter(({ value }) => value.length > 0);

  if (entries.length === 0) {
    return (
      <p className={cn("text-sm text-muted-foreground", className)}>
        Нет параметров для отображения.
      </p>
    );
  }

  return (
    <div className={cn("space-y-2", className)}>
      {SECTIONS.map((section) => {
        const sectionEntries = entries.filter(({ key }) => section.keys.includes(key));
        if (sectionEntries.length === 0) return null;
        return (
          <div key={section.id} className="space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground">
              {SECTION_TITLES[section.id]}
            </p>
            <div className="flex flex-wrap gap-2">
              {sectionEntries.map(({ key, value }) => (
                <span
                  key={key}
                  className="inline-flex items-start rounded-md border bg-background px-2.5 py-1 text-xs"
                >
                  <span className="text-muted-foreground">
                    {LABELS[key]}:
                  </span>
                  <span className="ml-1 font-medium">{value}</span>
                </span>
              ))}
            </div>
          </div>
        );
      })}
      {confidence != null && (
        <p className="text-xs text-muted-foreground">
          Уверенность разбора: {(confidence * 100).toFixed(0)}%
        </p>
      )}
    </div>
  );
}
