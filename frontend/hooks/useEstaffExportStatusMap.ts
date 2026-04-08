"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  fetchEstaffExportLatestBatch,
  type EstaffExportLatestBatchItem,
  type EstaffExportLatestResponse,
} from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";

function batchItemToResponse(it: EstaffExportLatestBatchItem): EstaffExportLatestResponse {
  return {
    found: it.found,
    export_id: it.export_id,
    candidate_id: it.candidate_id,
    hh_resume_id: it.hh_resume_id,
    status: it.status,
    estaff_candidate_id: it.estaff_candidate_id,
    error_message: it.error_message,
    error_stage: it.error_stage,
    preparation_warnings: it.preparation_warnings,
    exported_at: it.exported_at,
    created_at: it.created_at,
  };
}

/**
 * Один или несколько POST latest-batch по списку id резюме (чанки на клиенте).
 */
export function useEstaffExportStatusMap(hhResumeIds: string[]) {
  const accessToken = useAuthStore((s) => s.accessToken);
  const hasHydrated = useAuthStore((s) => s._hasHydrated);

  const sortedKey = useMemo(() => {
    const u = Array.from(
      new Set(
        hhResumeIds
          .map((x) => String(x).trim())
          .filter((s) => s.length > 0),
      ),
    ).sort();
    return JSON.stringify(u);
  }, [hhResumeIds]);

  const [map, setMap] = useState<Record<string, EstaffExportLatestResponse>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    if (!accessToken) {
      setMap({});
      setError(null);
      return;
    }
    const ids = (() => {
      try {
        return JSON.parse(sortedKey) as string[];
      } catch {
        return [] as string[];
      }
    })();
    if (ids.length === 0) {
      setMap({});
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const items = await fetchEstaffExportLatestBatch(ids);
      const next: Record<string, EstaffExportLatestResponse> = {};
      for (const it of items) {
        next[it.candidate_id] = batchItemToResponse(it);
      }
      setMap(next);
    } catch {
      setMap({});
      setError("Не удалось загрузить статус выгрузки e-staff");
    } finally {
      setLoading(false);
    }
  }, [accessToken, sortedKey]);

  useEffect(() => {
    if (!hasHydrated || !accessToken) {
      setMap({});
      setLoading(false);
      setError(null);
      return;
    }
    void refetch();
  }, [hasHydrated, accessToken, refetch]);

  return { map, loading, error, refetch };
}
