import type { Candidate } from "@/lib/types";

export type ListSortKind =
  | "server"
  | "llm_desc"
  | "llm_score_desc"
  | "experience_desc"
  | "experience_asc";

export const LIST_SORT_OPTIONS: { value: ListSortKind; label: string }[] = [
  { value: "server", label: "Как в выдаче" },
  { value: "llm_desc", label: "Оценка модели (выше сначала)" },
  { value: "llm_score_desc", label: "Быстрая оценка ИИ (выше сначала)" },
  { value: "experience_desc", label: "Опыт (больше сначала)" },
  { value: "experience_asc", label: "Опыт (меньше сначала)" },
];

function candidateSearchBlob(c: Candidate): string {
  const parts = [
    c.full_name,
    c.title,
    ...(Array.isArray(c.skills) ? c.skills : []),
  ];
  return parts.join(" ").toLowerCase();
}

export function filterCandidatesBySubstring(
  items: Candidate[],
  query: string,
): Candidate[] {
  const t = query.trim().toLowerCase();
  if (!t) return items;
  return items.filter((c) => candidateSearchBlob(c).includes(t));
}
