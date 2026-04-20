"use client";

import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  emptySearchFilters,
  type HhAreaOption,
  type HhProfessionalRoleOption,
  type SearchFiltersState,
} from "@/lib/search-filters";
import { cn } from "@/lib/utils";

const REGION_LIST_LIMIT = 80;
const REGION_IDLE_PREVIEW = 40;
const ROLE_LIST_LIMIT = 120;
const EMPTY_EXPERIENCE_VALUE = "__empty_experience__";
const EMPTY_GENDER_VALUE = "__empty_gender__";

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
  onChange: (areaIds: SearchFiltersState["area"]) => void;
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

  const selectedLabel = useMemo(() => {
    if (value.length === 0) return "Как в запросе / не задано";
    const selectedNames = value
      .map((areaId) => list.find((a) => a.id === areaId)?.name)
      .filter((name): name is string => Boolean(name));
    if (selectedNames.length === 1) return selectedNames[0];
    if (selectedNames.length > 1) return `Выбрано регионов: ${selectedNames.length}`;
    return `Выбрано регионов: ${value.length}`;
  }, [list, value]);

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
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  const toggleArea = (areaId: number) => {
    if (value.includes(areaId)) {
      onChange(value.filter((id) => id !== areaId));
      return;
    }
    onChange([...value, areaId]);
  };

  return (
    <div className="space-y-2" ref={rootRef}>
      <Label htmlFor="flt-area-search">Регион</Label>
      <button
        id="flt-area-search"
        type="button"
        className="flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 text-left text-sm"
        disabled={loading || list.length === 0}
        onClick={() => setOpen((prev) => !prev)}
      >
        <span className={cn("truncate", value.length === 0 && "text-muted-foreground")}>
          {loading ? "Загрузка справочника…" : selectedLabel}
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 opacity-50" />
      </button>
      {open &&
        !loading &&
        list.length > 0 &&
        menuBox &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            id="flt-area-search-menu"
            className="fixed z-[200] max-h-[min(16rem,55vh)] overflow-hidden rounded-md border border-input bg-background shadow-md"
            style={{
              top: menuBox.top,
              left: menuBox.left,
              width: menuBox.width,
            }}
          >
            <div className="border-b border-border p-2">
              <input
                type="search"
                autoComplete="off"
                placeholder="Поиск региона…"
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <div className="max-h-[min(11rem,40vh)] overflow-y-auto p-1">
              <button
                type="button"
                className="flex w-full items-center justify-between rounded-sm px-3 py-2 text-left text-sm hover:bg-accent hover:text-accent-foreground"
                onClick={() => onChange([])}
              >
                <span>Как в запросе / не задано</span>
                {value.length === 0 && <Check className="h-4 w-4" />}
              </button>
              {filtered.map((area) => {
                const selected = value.includes(area.id);
                return (
                  <button
                    key={area.id}
                    type="button"
                    className={cn(
                      "flex w-full items-center justify-between rounded-sm px-3 py-2 text-left text-sm hover:bg-accent hover:text-accent-foreground",
                      selected && "bg-accent text-accent-foreground",
                    )}
                    onClick={() => toggleArea(area.id)}
                  >
                    <span className="truncate pr-3">{area.name}</span>
                    {selected && <Check className="h-4 w-4 shrink-0" />}
                  </button>
                );
              })}
              {filtered.length === 0 && (
                <p className="px-3 py-2 text-sm text-muted-foreground">Нет совпадений</p>
              )}
            </div>
          </div>,
          document.body,
        )}
      {hint && <p className="text-xs text-amber-700 dark:text-amber-500">{hint}</p>}
    </div>
  );
}

function RoleMultiSelectField({
  value,
  roles,
  loading,
  hint,
  onChange,
}: {
  value: SearchFiltersState["professional_role"];
  roles: HhProfessionalRoleOption[];
  loading: boolean;
  hint: string | null;
  onChange: (roleIds: SearchFiltersState["professional_role"]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const [menuBox, setMenuBox] = useState<{
    top: number;
    left: number;
    width: number;
  } | null>(null);

  const list = useMemo(() => roles ?? [], [roles]);

  const selectedLabel = useMemo(() => {
    if (value.length === 0) return "Как в запросе / не задано";
    const selectedNames = value
      .map((roleId) => list.find((role) => role.id === roleId)?.name)
      .filter((name): name is string => Boolean(name));
    if (selectedNames.length === 1) return selectedNames[0];
    if (selectedNames.length > 1) return `Выбрано ролей: ${selectedNames.length}`;
    return `Выбрано ролей: ${value.length}`;
  }, [list, value]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return list.slice(0, ROLE_LIST_LIMIT);
    return list
      .filter((role) => role.name.toLowerCase().includes(q))
      .slice(0, ROLE_LIST_LIMIT);
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
      const menu = document.getElementById("flt-role-search-menu");
      if (el?.contains(t)) return;
      if (menu?.contains(t)) return;
      setOpen(false);
    };
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  const toggleRole = (roleId: number) => {
    if (value.includes(roleId)) {
      onChange(value.filter((id) => id !== roleId));
      return;
    }
    onChange([...value, roleId]);
  };

  return (
    <div className="space-y-2" ref={rootRef}>
      <Label htmlFor="flt-prof-role">Роль</Label>
      <button
        id="flt-prof-role"
        type="button"
        className="flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 text-left text-sm"
        disabled={loading || list.length === 0}
        onClick={() => setOpen((prev) => !prev)}
      >
        <span className={cn("truncate", value.length === 0 && "text-muted-foreground")}>
          {loading ? "Загрузка справочника…" : selectedLabel}
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 opacity-50" />
      </button>

      {open &&
        !loading &&
        list.length > 0 &&
        menuBox &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            id="flt-role-search-menu"
            className="fixed z-[200] max-h-[min(16rem,55vh)] overflow-hidden rounded-md border border-input bg-background shadow-md"
            style={{
              top: menuBox.top,
              left: menuBox.left,
              width: menuBox.width,
            }}
          >
            <div className="border-b border-border p-2">
              <input
                type="search"
                autoComplete="off"
                placeholder="Поиск роли…"
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>

            <div className="max-h-[min(11rem,40vh)] overflow-y-auto p-1">
              <button
                type="button"
                className="flex w-full items-center justify-between rounded-sm px-3 py-2 text-left text-sm hover:bg-accent hover:text-accent-foreground"
                onClick={() => onChange([])}
              >
                <span>Как в запросе / не задано</span>
                {value.length === 0 && <Check className="h-4 w-4" />}
              </button>

              {filtered.map((role) => {
                const selected = value.includes(role.id);
                return (
                  <button
                    key={role.id}
                    type="button"
                    className={cn(
                      "flex w-full items-center justify-between rounded-sm px-3 py-2 text-left text-sm hover:bg-accent hover:text-accent-foreground",
                      selected && "bg-accent text-accent-foreground",
                    )}
                    onClick={() => toggleRole(role.id)}
                  >
                    <span className="truncate pr-3">{role.name}</span>
                    {selected && <Check className="h-4 w-4 shrink-0" />}
                  </button>
                );
              })}

              {filtered.length === 0 && (
                <p className="px-3 py-2 text-sm text-muted-foreground">Нет совпадений</p>
              )}
            </div>
          </div>,
          document.body,
        )}

      {hint && <p className="text-xs text-amber-700 dark:text-amber-500">{hint}</p>}
    </div>
  );
}

type Props = {
  value: SearchFiltersState;
  onChange: (next: SearchFiltersState) => void;
  areas: HhAreaOption[];
  professionalRoles: HhProfessionalRoleOption[];
  professionalRolesLoading?: boolean;
  professionalRolesHint?: string | null;
  areasLoading?: boolean;
  areasHint?: string | null;
};

function FilterFields({
  value,
  onChange,
  areas,
  professionalRoles,
  professionalRolesLoading,
  professionalRolesHint,
  areasLoading,
  areasHint,
}: {
  value: SearchFiltersState;
  onChange: (next: SearchFiltersState) => void;
  areas: HhAreaOption[];
  professionalRoles: HhProfessionalRoleOption[];
  professionalRolesLoading?: boolean;
  professionalRolesHint?: string | null;
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

      <RoleMultiSelectField
        value={value.professional_role}
        roles={professionalRoles}
        loading={professionalRolesLoading ?? false}
        hint={professionalRolesHint ?? null}
        onChange={(professional_role) => patch({ professional_role })}
      />

      <div className="space-y-2">
        <Label htmlFor="flt-exp">Опыт работы</Label>
        <Select
          value={value.experience || EMPTY_EXPERIENCE_VALUE}
          onValueChange={(val) =>
            patch({
              experience:
                val === EMPTY_EXPERIENCE_VALUE
                  ? ""
                  : (val as SearchFiltersState["experience"]),
            })
          }
        >
          <SelectTrigger id="flt-exp">
            <SelectValue placeholder="Как в запросе / не задано" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={EMPTY_EXPERIENCE_VALUE}>Как в запросе / не задано</SelectItem>
            <SelectItem value="noExperience">Без опыта</SelectItem>
            <SelectItem value="between1And3">1–3 года</SelectItem>
            <SelectItem value="between3And6">3–6 лет</SelectItem>
            <SelectItem value="moreThan6">Более 6 лет</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <Label htmlFor="flt-gender">Пол</Label>
        <Select
          value={value.gender || EMPTY_GENDER_VALUE}
          onValueChange={(val) =>
            patch({
              gender: val === EMPTY_GENDER_VALUE ? "" : (val as SearchFiltersState["gender"]),
            })
          }
        >
          <SelectTrigger id="flt-gender">
            <SelectValue placeholder="Не задано" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={EMPTY_GENDER_VALUE}>Не задано</SelectItem>
            <SelectItem value="male">Мужской</SelectItem>
            <SelectItem value="female">Женский</SelectItem>
          </SelectContent>
        </Select>
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
        <Select
          value={value.currency}
          onValueChange={(val) => patch({ currency: val })}
        >
          <SelectTrigger id="flt-currency">
            <SelectValue placeholder="RUR" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="RUR">RUR</SelectItem>
            <SelectItem value="USD">USD</SelectItem>
            <SelectItem value="EUR">EUR</SelectItem>
          </SelectContent>
        </Select>
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
  professionalRoles,
  professionalRolesLoading,
  professionalRolesHint,
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
          Регион из панели фильтров имеет приоритет над регионом из текста запроса.
        </p>
        <FilterFields
          value={value}
          onChange={onChange}
          areas={areas}
          professionalRoles={professionalRoles}
          professionalRolesLoading={professionalRolesLoading}
          professionalRolesHint={professionalRolesHint}
          areasLoading={areasLoading}
          areasHint={areasHint}
        />
      </aside>
    </>
  );
}
