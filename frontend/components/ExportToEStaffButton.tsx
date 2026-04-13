"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { EstaffExportDialog } from "@/components/estaff/EstaffExportDialog";
import { Button } from "@/components/ui/button";
import type { LLMAnalysis } from "@/lib/types";
import {
  estaffLlmAnalysisHasPayload,
  fetchEstaffExportLatest,
  sanitizeApiErrorMessage,
  type EstaffExportLatestResponse,
  type EstaffHrBundleContext,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type Props = {
  hhResumeId: string;
  size?: "sm" | "default";
  variant?: "default" | "outline" | "secondary";
  className?: string;
  /**
   * Режим списка: статус с родителя (пакетный запрос).
   * undefined — страница кандидата, свой GET.
   * null — данные ещё не пришли.
   */
  parentEstaffLatest?: EstaffExportLatestResponse | null;
  /** После успешной выгрузки из диалога — обновить карту на странице списка */
  onEstaffStatusUpdated?: () => void;
  /** По умолчанию true — тост при ошибке статуса и тосты диалога выгрузки */
  showToastNotifications?: boolean;
  hrLlmSummary?: string | null;
  hrLlmScore?: number | null;
  hrLlmAnalysis?: LLMAnalysis | null;
  hrSearchQuery?: string | null;
};

export function ExportToEStaffButton({
  hhResumeId,
  size = "sm",
  variant = "outline",
  className,
  parentEstaffLatest,
  onEstaffStatusUpdated,
  showToastNotifications = true,
  hrLlmSummary = null,
  hrLlmScore = null,
  hrLlmAnalysis = null,
  hrSearchQuery = null,
}: Props) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [hint, setHint] = useState<string | null>(null);
  const [positive, setPositive] = useState(false);
  const errorToastSentForResume = useRef<string | null>(null);

  const applyFromResponse = useCallback(
    (s: EstaffExportLatestResponse, resumeId: string) => {
      if (s.found && s.status === "success") {
        setPositive(true);
        errorToastSentForResume.current = null;
        setHint(
          s.estaff_candidate_id
            ? `Уже выгружено (e-staff: ${s.estaff_candidate_id})`
            : "Уже выгружено в e-staff",
        );
      } else if (s.found && s.status === "error") {
        setPositive(false);
        const key = `${resumeId}:${s.error_message ?? ""}`;
        if (errorToastSentForResume.current !== key) {
          if (showToastNotifications) {
            toast.error(sanitizeApiErrorMessage(s.error_message));
          }
          errorToastSentForResume.current = key;
        }
        setHint("Выгрузка не удалась");
      } else {
        setPositive(false);
        errorToastSentForResume.current = null;
        setHint(null);
      }
    },
    [showToastNotifications],
  );

  const refreshStatus = useCallback(async () => {
    const id = hhResumeId.trim();
    if (!id) return;
    try {
      const s = await fetchEstaffExportLatest(id);
      applyFromResponse(s, id);
    } catch {
      setHint(null);
      setPositive(false);
      errorToastSentForResume.current = null;
    }
  }, [hhResumeId, applyFromResponse]);

  const useParent = parentEstaffLatest !== undefined;

  useEffect(() => {
    if (useParent) return;
    void refreshStatus();
  }, [useParent, refreshStatus]);

  useEffect(() => {
    if (!useParent) return;
    const id = hhResumeId.trim();
    if (!id) return;
    if (parentEstaffLatest === null) {
      setHint(null);
      setPositive(false);
      errorToastSentForResume.current = null;
      return;
    }
    applyFromResponse(parentEstaffLatest, id);
  }, [useParent, parentEstaffLatest, hhResumeId, applyFromResponse]);

  const handleExportSuccess = useCallback(() => {
    if (useParent) {
      onEstaffStatusUpdated?.();
      return;
    }
    void refreshStatus();
  }, [useParent, onEstaffStatusUpdated, refreshStatus]);

  const id = hhResumeId.trim();
  const hasBundleCtx =
    Boolean(id) &&
    (Boolean(hrLlmSummary?.trim()) ||
      hrLlmScore != null ||
      estaffLlmAnalysisHasPayload(hrLlmAnalysis) ||
      Boolean(hrSearchQuery?.trim()));
  const hrBundleContextByResumeId: Record<string, EstaffHrBundleContext> | undefined =
    hasBundleCtx && id
      ? {
          [id]: {
            ...(hrLlmSummary != null && hrLlmSummary !== ""
              ? { hr_llm_summary: hrLlmSummary }
              : {}),
            ...(hrLlmScore != null ? { hr_llm_score: hrLlmScore } : {}),
            ...(estaffLlmAnalysisHasPayload(hrLlmAnalysis) && hrLlmAnalysis
              ? { hr_llm_analysis: hrLlmAnalysis }
              : {}),
            ...(hrSearchQuery != null && hrSearchQuery.trim() !== ""
              ? { hr_search_query: hrSearchQuery.trim() }
              : {}),
          },
        }
      : undefined;

  return (
    <div className={cn("min-w-0", className)}>
      <Button
        type="button"
        size={size}
        variant={variant}
        disabled={!hhResumeId.trim()}
        onClick={() => setDialogOpen(true)}
      >
        Выгрузить в e-staff
      </Button>
      {hint ? (
        <p
          className={cn(
            "mt-1 text-xs",
            positive
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-destructive",
          )}
        >
          {hint}
        </p>
      ) : null}
      <EstaffExportDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        resumeIds={[hhResumeId.trim()].filter(Boolean)}
        showToastNotifications={showToastNotifications}
        hrBundleContextByResumeId={hrBundleContextByResumeId}
        onSuccess={handleExportSuccess}
      />
    </div>
  );
}
