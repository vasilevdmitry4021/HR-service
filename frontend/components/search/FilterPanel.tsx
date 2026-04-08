"use client";

import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  emptySearchFilters,
  type HhAreaOption,
  type SearchFiltersState,
} from "@/lib/search-filters";
import { cn } from "@/lib/utils";

const REGION_LIST_LIMIT = 80;
const REGION_IDLE_PREVIEW = 40;

function RegionSearchField({
  value,
  areas,
  loading,
  hint,
  onChange,
}: {
  value: SearchFiltersState["area"];
  areas: HhAreaOption[];
  loading: boolean;
  hint: string | null;
  onChange: (area: SearchFiltersState["area"]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const [menuBox, setMenuBox] = useState<{
    top: number;
    left: number;
    width: number;
  } | null>(null);

  const list = useMemo(() => areas ?? [], [areas]);

  const selectedName =
    value !== "" ? list.find((a) => a.id === value)?.name : null;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) {
      return list.slice(0, REGION_IDLE_PREVIEW);
    }
    return list
      .filter((a) => a.name.toLowerCase().includes(q))
      .slice(0, REGION_LIST_LIMIT);
  }, [list, query]);

  useLayoutEffect(() => {
    if (!open || !rootRef.current) {
      setMenuBox(null);
      return;
    }
    const el = rootRef.current;
    const update = () => {
      const r = el.getBoundingClientRect();
      setMenuBox({ top: r.bottom + 4, left: r.left, width: r.width });
    };
    update();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      const el = rootRef.current;
      const menu = document.getElementById("flt-area-search-menu");
      if (el?.contains(t)) return;
      if (menu?.contains(t)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div className="space-y-2" ref={rootRef}>
      <Label htmlFor="flt-area-search">Регион</Label>
      <div className="relative">
        <input
          id="flt-area-search"
          type="search"
          autoComplete="off"
          disabled={loading || list.length === 0}
          placeholder={
            loading ? "Загрузка справочника…" : "Начните вводить город или регион…"
          }
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
          value={open ? query : selectedName ?? ""}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => {
            setOpen(true);
            setQuery("");
          }}
        />
        {open &&
          !loading &&
          list.length > 0 &&
          menuBox &&
          typeof document !== "undefined" &&
          createPortal(
            <ul
              id="flt-area-search-menu"
              className="fixed z-[200] max-h-[min(13rem,45vh)] overflow-y-auto rounded-md border border-input bg-background py-1 text-sm shadow-md"
              style={{
                top: menuBox.top,
                left: menuBox.left,
                width: menuBox.width,
              }}
              role="listbox"
            >
              <li role="option" aria-selected={value === ""}>
                <button
                  type="button"
                  className="w-full px-3 py-2 text-left hover:bg-muted"
                  onClick={() => {
                    onChange("");
                    setOpen(false);
                    setQuery("");
                  }}
                >
                  Не задано
                </button>
              </li>
              {filtered.map((a) => (
                <li key={a.id} role="option" aria-selected={value === a.id}>
                  <button
                    type="button"
                    className="w-full px-3 py-2 text-left hover:bg-muted"
                    onClick={() => {
                      onChange(a.id);
                      setOpen(false);
                      setQuery("");
                    }}
                  >
                    {a.name}
                  </button>
                </li>
              ))}
              {filtered.length === 0 && (
                <li className="px-3 py-2 text-muted-foreground">Нет совпадений</li>
              )}
            </ul>,
            document.body,
          )}
      </div>
      {hint && <p className="text-xs text-amber-700 dark:text-amber-500">{hint}</p>}
      {value !== "" && selectedName && !open && (
        <p className="text-xs text-muted-foreground">
          Идентификатор в HeadHunter: {value}
        </p>
      )}
    </div>
  );
}

type Props = {
  value: SearchFiltersState;
  onChange: (next: SearchFiltersState) => void;
  areas: HhAreaOption[];
  areasLoading?: boolean;
  areasHint?: string | null;
};

function FilterFields({
  value,
  onChange,
  areas,
  areasLoading,
  areasHint,
}: {
  value: SearchFiltersState;
  onChange: (next: SearchFiltersState) => void;
  areas: HhAreaOption[];
  areasLoading?: boolean;
  areasHint?: string | null;
}) {
  const patch = (partial: Partial<SearchFiltersState>) =>
    onChange({ ...value, ...partial });

  return (
    <div className="space-y-4">
      <RegionSearchField
        value={value.area}
        areas={areas}
        loading={areasLoading ?? false}
        hint={areasHint ?? null}
        onChange={(area) => patch({ area })}
      />

      <div className="space-y-2">
        <Label htmlFor="flt-exp">Опыт работы</Label>
        <select
          id="flt-exp"
          className="select-chevron flex h-10 w-full rounded-md border border-input bg-background pl-3 text-sm"
          value={value.experience}
          onChange={(e) =>
            patch({
              experience: e.target.value as SearchFiltersState["experience"],
            })
          }
        >
          <option value="">Как в запросе / не задано</option>
          <option value="noExperience">Без опыта</option>
          <option value="between1And3">1–3 года</option>
          <option value="between3And6">3–6 лет</option>
          <option value="moreThan6">Более 6 лет</option>
        </select>
      </div>

      <div className="space-y-2">
        <Label htmlFor="flt-gender">Пол</Label>
        <select
          id="flt-gender"
          className="select-chevron flex h-10 w-full rounded-md border border-input bg-background pl-3 text-sm"
          value={value.gender}
          onChange={(e) =>
            patch({ gender: e.target.value as SearchFiltersState["gender"] })
          }
        >
          <option value="">Не задано</option>
          <option value="male">Мужской</option>
          <option value="female">Женский</option>
        </select>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          <Label htmlFor="flt-age-from">Возраст от</Label>
          <input
            id="flt-age-from"
            type="number"
            min={14}
            max={100}
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
            value={value.age_from}
            onChange={(e) => patch({ age_from: e.target.value })}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="flt-age-to">Возраст до</Label>
          <input
            id="flt-age-to"
            type="number"
            min={14}
            max={100}
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
            value={value.age_to}
            onChange={(e) => patch({ age_to: e.target.value })}
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          <Label htmlFor="flt-sal-from">Зарплата от</Label>
          <input
            id="flt-sal-from"
            type="number"
            min={0}
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
            value={value.salary_from}
            onChange={(e) => patch({ salary_from: e.target.value })}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="flt-sal-to">Зарплата до</Label>
          <input
            id="flt-sal-to"
            type="number"
            min={0}
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
            value={value.salary_to}
            onChange={(e) => patch({ salary_to: e.target.value })}
          />
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="flt-currency">Валюта</Label>
        <select
          id="flt-currency"
          className="select-chevron flex h-10 w-full rounded-md border border-input bg-background pl-3 text-sm"
          value={value.currency}
          onChange={(e) => patch({ currency: e.target.value })}
        >
          <option value="RUR">RUR</option>
          <option value="USD">USD</option>
          <option value="EUR">EUR</option>
        </select>
      </div>

      <Button
        type="button"
        variant="outline"
        className="w-full"
        onClick={() => onChange(emptySearchFilters())}
      >
        Сбросить фильтры
      </Button>
    </div>
  );
}

export function FilterPanel({
  value,
  onChange,
  areas,
  areasLoading,
  areasHint,
}: Props) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const onChangeMq = () => {
      if (mq.matches) setOpen(false);
    };
    mq.addEventListener("change", onChangeMq);
    return () => mq.removeEventListener("change", onChangeMq);
  }, []);

  return (
    <>
      <div className="flex items-center justify-between gap-2 lg:hidden">
        <h2 className="text-sm font-medium text-muted-foreground">Фильтры</h2>
        <Button type="button" size="sm" variant="outline" onClick={() => setOpen(true)}>
          Открыть панель
        </Button>
      </div>

      {open && (
        <button
          type="button"
          aria-label="Закрыть фильтры"
          className="fixed inset-0 z-40 bg-background/80 backdrop-blur-sm lg:hidden"
          onClick={() => setOpen(false)}
        />
      )}

      <aside
        className={cn(
          "border-border bg-card text-card-foreground",
          "fixed inset-y-0 right-0 z-50 w-full max-w-sm overflow-y-auto border-l p-4 shadow-xl transition-transform duration-200 ease-out",
          "lg:static lg:z-0 lg:max-w-none lg:w-72 lg:shrink-0 lg:rounded-lg lg:border lg:shadow-sm",
          open ? "translate-x-0" : "translate-x-full lg:translate-x-0",
        )}
      >
        <div className="mb-4 flex items-center justify-between lg:mb-2">
          <h2 className="text-base font-semibold">Фильтры поиска</h2>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="lg:hidden"
            onClick={() => setOpen(false)}
          >
            Закрыть
          </Button>
        </div>
        <p className="mb-4 text-xs text-muted-foreground">
          Фильтры задаются в панели и отображаются компактно под полем поиска.
          Синхронизация с текстом используется для шаблонов и истории.
        </p>
        <FilterFields
          value={value}
          onChange={onChange}
          areas={areas}
          areasLoading={areasLoading}
          areasHint={areasHint}
        />
      </aside>
    </>
  );
}
