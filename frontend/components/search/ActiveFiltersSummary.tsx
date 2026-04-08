"use client";

import {
  FALLBACK_AREA_OPTIONS,
  filtersToReadableSummary,
  type SearchFiltersState,
} from "@/lib/search-filters";

type Props = {
  filters: SearchFiltersState;
  parsedRegion?: string | null;
  /** Подписи регионов из справочника (id → название) */
  areaLabels?: Map<number, string>;
};

/** Компактный блок активных фильтров под полем поиска */
export function ActiveFiltersSummary({
  filters,
  parsedRegion,
  areaLabels,
}: Props) {
  const items = filtersToReadableSummary(filters, areaLabels);

  const filterAreaLabel =
    filters.area === ""
      ? null
      : (areaLabels?.get(filters.area) ??
          FALLBACK_AREA_OPTIONS.find((a) => a.id === filters.area)?.name ??
          `Регион №${filters.area}`);

  const hasRegionConflict =
    filterAreaLabel &&
    parsedRegion &&
    parsedRegion.trim().toLowerCase() !== filterAreaLabel.toLowerCase();

  if (items.length === 0 && !hasRegionConflict) return null;

  return (
    <div className="space-y-1">
      {items.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Активные фильтры: {items.join(" · ")}
        </p>
      )}
      {hasRegionConflict && (
        <p className="text-xs text-amber-600">
          В запросе указан регион «{parsedRegion}», но в фильтрах выбран «
          {filterAreaLabel}». Поиск будет выполнен по фильтру.
        </p>
      )}
    </div>
  );
}
