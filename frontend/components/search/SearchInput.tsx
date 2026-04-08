"use client";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

export function SearchInput(props: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  loading?: boolean;
  parsing?: boolean;
  placeholder?: string;
  className?: string;
  onClear?: () => void;
  showClear?: boolean;
}) {
  const {
    value,
    onChange,
    onSubmit,
    loading,
    parsing,
    placeholder,
    className,
    onClear,
    showClear,
  } = props;
  const ph =
    placeholder ?? "Например: Java developer, 3+ года, Москва";
  const busy = Boolean(loading || parsing);
  return (
    <div className={cn("flex flex-col gap-3", className)}>
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start">
        <Textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={ph}
          rows={4}
          aria-label="Поисковый запрос"
          onKeyDown={(e) => {
            if (
              e.key === "Enter" &&
              (e.ctrlKey || e.metaKey) &&
              !busy
            ) {
              e.preventDefault();
              onSubmit();
            }
          }}
          disabled={busy}
          className="sm:min-w-0 sm:flex-1 text-base"
          aria-busy={busy}
        />
        <div className="flex flex-col gap-2 sm:flex-row lg:flex-shrink-0 lg:flex-col lg:gap-2">
          {showClear && onClear && !busy ? (
            <Button type="button" variant="outline" onClick={onClear} size="lg">
              Очистить
            </Button>
          ) : null}
          <Button type="button" onClick={onSubmit} disabled={busy} size="lg">
            {loading ? "Поиск…" : parsing ? "Обработка…" : "Найти"}
          </Button>
        </div>
      </div>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span>Enter — новая строка</span>
        <span className="text-border">•</span>
        <span>Ctrl+Enter — запуск поиска</span>
      </div>
      {(parsing || loading) && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground animate-fade-in" role="status">
          <div className="h-1 w-1 rounded-full bg-primary animate-pulse" />
          <span>{parsing ? "Анализ запроса…" : "Поиск кандидатов…"}</span>
        </div>
      )}
    </div>
  );
}
