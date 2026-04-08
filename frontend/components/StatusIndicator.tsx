"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import type { HHStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

export function StatusIndicator({ className }: { className?: string }) {
  const [status, setStatus] = useState<HHStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch<HHStatus>("/hh/status");
        if (!cancelled) setStatus(data);
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : "Ошибка");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <Badge variant="outline" pulse dot className={className}>
        HH: проверка
      </Badge>
    );
  }
  if (err) {
    return (
      <Badge variant="destructive" className={className}>
        HH: ошибка
      </Badge>
    );
  }
  if (!status || !status.connected) {
    return (
      <Badge variant="warning" className={className}>
        HH: не подключен
      </Badge>
    );
  }
  const extra = status.employer_name ? ` • ${status.employer_name}` : "";
  return (
    <Badge variant="success" dot className={className}>
      HH: подключен{extra}
    </Badge>
  );
}
