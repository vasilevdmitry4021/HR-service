"use client";

import { useEffect, useState } from "react";
import {
  apiFetch,
  fetchEstaffCredentialsStatus,
  fetchLLMSettingsStatus,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import type { HHStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

type Slice<T> =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; data: T };

type HhSlice = Slice<HHStatus>;
type BoolSlice = Slice<{ configured: boolean }>;

function errMessage(e: unknown): string {
  return e instanceof Error ? e.message : "Ошибка";
}

export function StatusIndicator({ className }: { className?: string }) {
  const [hh, setHh] = useState<HhSlice>({ phase: "loading" });
  const [llm, setLlm] = useState<BoolSlice>({ phase: "loading" });
  const [estaff, setEstaff] = useState<BoolSlice>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [hhR, llmR, esR] = await Promise.allSettled([
        apiFetch<HHStatus>("/hh/status"),
        fetchLLMSettingsStatus(),
        fetchEstaffCredentialsStatus(),
      ]);
      if (cancelled) return;

      if (hhR.status === "fulfilled") {
        setHh({ phase: "ready", data: hhR.value });
      } else {
        setHh({ phase: "error", message: errMessage(hhR.reason) });
      }

      if (llmR.status === "fulfilled") {
        setLlm({
          phase: "ready",
          data: { configured: Boolean(llmR.value.configured) },
        });
      } else {
        setLlm({ phase: "error", message: errMessage(llmR.reason) });
      }

      if (esR.status === "fulfilled") {
        setEstaff({
          phase: "ready",
          data: { configured: Boolean(esR.value.configured) },
        });
      } else {
        setEstaff({ phase: "error", message: errMessage(esR.reason) });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-end gap-2",
        className,
      )}
    >
      <HhBadge slice={hh} />
      <ConfiguredBadge label="ИИ" slice={llm} />
      <ConfiguredBadge label="e-staff" slice={estaff} />
    </div>
  );
}

function HhBadge({ slice }: { slice: HhSlice }) {
  if (slice.phase === "loading") {
    return (
      <Badge variant="outline" pulse dot>
        HH: проверка
      </Badge>
    );
  }
  if (slice.phase === "error") {
    return (
      <Badge variant="destructive" title={slice.message}>
        HH: ошибка
      </Badge>
    );
  }
  const status = slice.data;
  if (!status.connected) {
    return (
      <Badge variant="warning">
        HH: не подключен
      </Badge>
    );
  }
  const extra = status.employer_name ? ` • ${status.employer_name}` : "";
  return (
    <Badge variant="success" dot>
      HH: подключен{extra}
    </Badge>
  );
}

function ConfiguredBadge({
  label,
  slice,
}: {
  label: string;
  slice: BoolSlice;
}) {
  if (slice.phase === "loading") {
    return (
      <Badge variant="outline" pulse dot>
        {label}: проверка
      </Badge>
    );
  }
  if (slice.phase === "error") {
    return (
      <Badge variant="destructive" title={slice.message}>
        {label}: ошибка
      </Badge>
    );
  }
  if (!slice.data.configured) {
    return (
      <Badge variant="warning">
        {label}: не подключен
      </Badge>
    );
  }
  return (
    <Badge variant="success" dot>
      {label}: подключен
    </Badge>
  );
}
