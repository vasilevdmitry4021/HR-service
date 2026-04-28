export type ParsedParams = Record<string, unknown>;
export type SearchMode = "precise" | "mass";

export type LLMAnalysis = {
  llm_score: number | null;
  is_relevant: boolean | null;
  strengths: string[];
  gaps: string[];
  summary: string | null;
};

export type Candidate = {
  id: string;
  hh_resume_id: string;
  hh_resume_url?: string | null;
  source_type?: "hh";
  candidate_profile_id?: string | null;
  /** Внешний идентификатор в контуре источника */
  source_resume_id?: string | null;
  title: string;
  full_name: string;
  age?: number | null;
  experience_years?: number | null;
  salary?: {
    amount?: number | null;
    from?: number | null;
    to?: number | null;
    currency?: string | null;
    gross?: boolean | null;
  } | null;
  skills: string[];
  area: string;
  /** Появляется после POST /search/{snapshot_id}/evaluate (pre-screening) */
  llm_score?: number | null;
  llm_analysis?: LLMAnalysis | null;
  parse_confidence?: number | null;
  parse_warnings?: string[];
  incompleteness_flags?: string[];
};

export type SearchMetrics = {
  area?: {
    effective?: number | null;
    effective_ids?: number[];
    source?: "panel" | "parsed_region" | "none" | string;
    parsed_region?: string | null;
  };
  primary_found?: number;
  relax_steps_used?: number;
  raw_pool_size?: number;
  count_after_strict_filter?: number;
  recall_target_min_base?: number;
  recall_target_min_used?: number;
  search_mode?: SearchMode;
  role_strategy?: string;
  skills_strategy?: string;
  text_operator?: "AND" | "OR" | string;
  professional_role_ids?: number[];
  skill_ids?: number[];
  text_terms?: string[];
  [key: string]: unknown;
};

export type SearchResponse = {
  items: Candidate[];
  found: number;
  page: number;
  pages: number;
  per_page: number;
  parsed_params: ParsedParams;
  snapshot_id?: string | null;
  found_raw_hh?: number | null;
  search_metrics?: SearchMetrics | null;
  source_scope?: "hh";
  search_mode?: SearchMode;
};

/** Ответ POST /search/{snapshot_id}/evaluate — только id резюме и числовой балл */
export type EvaluateCandidateRow = {
  id: string;
  llm_score: number | null;
};

export type EvaluateSnapshotResponse = {
  items: EvaluateCandidateRow[];
  evaluated_count: number;
  llm_scored_count: number;
  fallback_scored_count: number;
  coverage_ratio: number;
  processing_time_seconds: number;
  metrics?: Record<string, unknown>;
};

export type EvaluateStartResponse = {
  job_id: string;
  status: string;
  total_count: number;
};

export type EvaluateProgressResponse = {
  job_id: string;
  status: "queued" | "running" | "done" | "partial" | "error" | string;
  stage: string;
  phase: "interactive" | "background" | "done" | string;
  total_count: number;
  scored_count: number;
  llm_scored_count: number;
  fallback_scored_count: number;
  coverage_ratio: number;
  llm_coverage_ratio: number;
  unresolved_count: number;
  llm_only_complete: boolean;
  completed_count: number;
  interactive_total_count: number;
  background_total_count: number;
  interactive_done_count: number;
  background_done_count: number;
  interactive_llm_scored_count: number;
  background_llm_scored_count: number;
  interactive_fallback_count: number;
  background_fallback_count: number;
  items: EvaluateCandidateRow[];
  processing_time_seconds?: number | null;
  error?: string | null;
  metrics?: Record<string, unknown>;
};

export type AnalyzeSnapshotResponse = {
  items: Candidate[];
  analyzed_count: number;
  processing_time_seconds: number;
  metrics?: Record<string, unknown>;
};

export type AnalyzeStartResponse = {
  job_id: string;
  status: string;
  total_count: number;
};

export type AnalyzeProgressResponse = {
  job_id: string;
  status: string;
  stage: string;
  phase: string;
  total_count: number;
  processed_count: number;
  analyzed_count: number;
  phase_total_count: number;
  phase_done_count: number;
  enriched_count: number;
  progress_percent: number;
  analyses: Record<string, LLMAnalysis>;
  metrics?: Record<string, unknown>;
  processing_time_seconds?: number | null;
  error?: string | null;
};

export type HHStatus = {
  connected: boolean;
  hh_user_id?: string | null;
  employer_name?: string | null;
  access_expires_at?: string | null;
  services?: Record<string, unknown> | null;
  message?: string | null;
};

export type FavoriteRow = {
  id: string;
  hh_resume_id: string | null;
  candidate_id?: string | null;
  title_snapshot: string | null;
  full_name: string | null;
  contact_email?: string | null;
  contact_phone?: string | null;
  area: string | null;
  skills_snapshot: string[] | null;
  experience_years: number | null;
  age: number | null;
  salary_amount: number | null;
  salary_currency: string | null;
  llm_score: number | null;
  llm_summary: string | null;
  llm_analysis?: LLMAnalysis | null;
  notes: string;
  created_at: string;
  updated_at: string;
};

export type FavoriteRefreshMeta = {
  contacts_unlocked: boolean;
  full_name_updated: boolean;
  message?: string | null;
};

export type FavoriteRefreshResponse = {
  favorite: FavoriteRow;
  meta: FavoriteRefreshMeta;
};

export type WorkExperienceItem = {
  company: string;
  position: string;
  start?: string | null;
  end?: string | null;
  period_label?: string | null;
  area?: string | null;
  industry?: string | null;
  description?: string | null;
};

export type EducationItem = {
  level?: string | null;
  organization?: string | null;
  speciality?: string | null;
  year?: string | null;
  summary?: string | null;
};

export type CandidateDetail = Candidate & {
  favorite_id: string | null;
  favorite_notes: string | null;
  work_experience?: WorkExperienceItem[];
  about?: string | null;
  education?: EducationItem[];
};

export type SearchHistoryRow = {
  id: string;
  query: string;
  filters: Record<string, unknown> | null;
  parsed_params: ParsedParams;
  page: number;
  per_page: number;
  found: number;
  created_at: string;
};

export type SearchHistoryListResponse = {
  items: SearchHistoryRow[];
  total: number;
};

export type SearchTemplateRow = {
  id: string;
  name: string;
  query: string;
  filters: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type IntegrationCallRecord = {
  system: string;
  operation: string;
  duration_ms: number;
  status_code: number | null;
  cached: boolean;
  error?: string | null;
};

export type RequestLogEntry = {
  id: string;
  request_id: string;
  query_id: string | null;
  user_id: string | null;
  user_email: string | null;
  method: string;
  route: string;
  route_tag: string;
  status_code: number;
  duration_ms: number;
  request_body_summary: Record<string, unknown> | null;
  response_summary: Record<string, unknown> | null;
  search_metrics: Record<string, unknown> | null;
  integration_calls: IntegrationCallRecord[] | null;
  error_type: string | null;
  error_message: string | null;
  created_at: string;
};

export type RequestLogList = {
  items: RequestLogEntry[];
  total: number;
};

export type RequestLogByRouteTag = {
  route_tag: string;
  count: number;
  error_count: number;
  avg_duration_ms: number;
};

export type RequestLogByDay = {
  date: string;
  count: number;
  error_count: number;
  avg_duration_ms: number;
};

export type RequestLogTopError = {
  error_type: string;
  error_message: string | null;
  count: number;
};

export type RequestLogIntegrationSummary = {
  system: string;
  call_count: number;
  avg_duration_ms: number;
  error_rate: number;
};

export type RequestLogStats = {
  total_requests: number;
  success_count: number;
  error_count: number;
  avg_duration_ms: number;
  p95_duration_ms: number;
  by_route_tag: RequestLogByRouteTag[];
  by_day: RequestLogByDay[];
  top_errors: RequestLogTopError[];
  integration_summary: RequestLogIntegrationSummary[];
};

export type RequestLogErrorGroup = {
  error_type: string;
  error_message: string | null;
  count: number;
  last_seen: string;
  route_tags: string[];
  affected_users_count: number;
};

export type RequestLogErrorsList = {
  items: RequestLogErrorGroup[];
};
