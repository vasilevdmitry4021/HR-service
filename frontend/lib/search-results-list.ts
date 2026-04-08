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

function effectiveModelScore(c: Candidate): number | null {
  return c.llm_score ?? c.llm_analysis?.llm_score ?? null;
}

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

function cmpLlmScoreDesc(a: Candidate, b: Candidate): number {
  const sa = effectiveModelScore(a);
  const sb = effectiveModelScore(b);
  const aOk = sa != null;
  const bOk = sb != null;
  if (!aOk && !bOk) return 0;
  if (!aOk) return 1;
  if (!bOk) return -1;
  return (sb as number) - (sa as number);
}

function cmpExperience(a: Candidate, b: Candidate, desc: boolean): number {
  const ea = a.experience_years;
  const eb = b.experience_years;
  const aOk = ea != null;
  const bOk = eb != null;
  if (!aOk && !bOk) return 0;
  if (!aOk) return 1;
  if (!bOk) return -1;
  const na = ea as number;
  const nb = eb as number;
  return desc ? nb - na : na - nb;
}

export function sortCandidates(items: Candidate[], kind: ListSortKind): Candidate[] {
  if (kind === "server") return items;
  const copy = [...items];
  switch (kind) {
    case "llm_desc":
    case "llm_score_desc":
      copy.sort(cmpLlmScoreDesc);
      break;
    case "experience_desc":
      copy.sort((a, b) => cmpExperience(a, b, true));
      break;
    case "experience_asc":
      copy.sort((a, b) => cmpExperience(a, b, false));
      break;
    default:
      break;
  }
  return copy;
}

export function processCandidatesForList(
  items: Candidate[],
  listFilter: string,
  listSort: ListSortKind,
): Candidate[] {
  return sortCandidates(
    filterCandidatesBySubstring(items, listFilter),
    listSort,
  );
}
