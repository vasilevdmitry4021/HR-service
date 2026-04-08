"use client";

import { Button } from "@/components/ui/button";
import type { SearchTemplateRow } from "@/lib/types";

type Props = {
  templates: SearchTemplateRow[];
  onApply: (t: SearchTemplateRow) => void;
  onDelete: (id: string) => void | Promise<void>;
  onSaveCurrent: () => void;
  canSave: boolean;
};

export function TemplatesPanel({
  templates,
  onApply,
  onDelete,
  onSaveCurrent,
  canSave,
}: Props) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b px-4 py-3">
        <h2 className="text-lg font-semibold tracking-tight">Шаблоны поиска</h2>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={!canSave}
          onClick={onSaveCurrent}
        >
          Сохранить текущий
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {templates.length === 0 ? (
          <div className="rounded-lg border border-dashed bg-muted/30 px-4 py-8 text-sm">
            <p className="font-medium text-foreground">Пока нет сохранённых шаблонов</p>
            <p className="mt-2 text-muted-foreground">
              Сохраните частый запрос и фильтры кнопкой выше — затем применяйте набор одним нажатием.
            </p>
          </div>
        ) : (
          <ul className="flex flex-col gap-3">
            {templates.map((t) => (
              <li
                key={t.id}
                className="rounded-lg border bg-card/50 p-3 shadow-sm"
              >
                <p className="font-medium leading-tight" title={t.name}>
                  {t.name}
                </p>
                <p
                  className="mt-1 line-clamp-2 text-xs text-muted-foreground"
                  title={t.query}
                >
                  {t.query || "—"}
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={() => onApply(t)}
                  >
                    Применить
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="text-destructive hover:text-destructive"
                    onClick={() => void onDelete(t.id)}
                  >
                    Удалить
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
