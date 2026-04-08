export type ParsedParams = Record<string, unknown>;

export type LLMAnalysis = {
  llm_score: number | null;
  is_relevant: boolean | null;
  strengths: string[];
  gaps: string[];
  summary: string | null;
};

/** Метаданные источника Telegram в карточке кандидата */
export type TelegramSourceMeta = {
  source_id?: string;
  source_display_name?: string;
  channel_or_chat_link?: string | null;
  telegram_message_id?: number;
  message_link?: string | null;
  published_at?: string | null;
};

/** Вложение Telegram (файл и превью извлечённого текста) */
export type TelegramAttachmentMeta = {
  file_type?: string;
  file_path?: string;
  file_hash?: string;
  filename?: string | null;
  extracted_preview?: string | null;
};

export type Candidate = {
  id: string;
  hh_resume_id: string;
  hh_resume_url?: string | null;
  source_type?: "hh" | "telegram";
  candidate_profile_id?: string | null;
  /** Внешний идентификатор в контуре источника (Telegram: id сообщения в БД) */
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
  telegram_sources?: TelegramSourceMeta[];
  telegram_attachments?: TelegramAttachmentMeta[];
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
  found_telegram?: number | null;
  source_scope?: "hh" | "telegram" | "all";
};

/** Ответ POST /search/{snapshot_id}/evaluate — только id резюме и числовой балл */
export type EvaluateCandidateRow = {
  id: string;
  llm_score: number | null;
};

export type EvaluateSnapshotResponse = {
  items: EvaluateCandidateRow[];
  evaluated_count: number;
  processing_time_seconds: number;
};

export type AnalyzeSnapshotResponse = {
  items: Candidate[];
  analyzed_count: number;
  processing_time_seconds: number;
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
  area: string | null;
  skills_snapshot: string[] | null;
  experience_years: number | null;
  age: number | null;
  salary_amount: number | null;
  salary_currency: string | null;
  llm_score: number | null;
  llm_summary: string | null;
  notes: string;
  created_at: string;
  updated_at: string;
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
  /** Исходный текст сообщения и извлечённого текста вложений (Telegram) */
  raw_message_text?: string | null;
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
