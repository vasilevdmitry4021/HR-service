"use client";

import {
  FALLBACK_AREA_OPTIONS,
  filtersToReadableSummary,
  type SearchFiltersState,
} from "@/lib/search-filters";

type Props = {
  filters: SearchFiltersState;
  parsedRegion?: string | null;
  effectiveAreaIds?: number[] | null;
  effectiveAreaSource?: "panel" | "parsed_region" | "none" | string;
  /** Подписи регионов из справочника (id → название) */
  areaLabels?: Map<number, string>;
  /** Подписи ролей из справочника (id → название) */
  roleLabels?: Map<number, string>;
};

/** Компактный блок активных фильтров под полем поиска */
export function ActiveFiltersSummary({
  filters,
  parsedRegion,
  effectiveAreaIds,
  effectiveAreaSource,
  areaLabels,
  roleLabels,
}: Props) {
  const items = filtersToReadableSummary(filters, areaLabels, roleLabels);

  const filterAreaLabel =
    filters.area.length === 0
      ? null
      : filters.area
          .map(
            (areaId) =>
              areaLabels?.get(areaId) ??
              FALLBACK_AREA_OPTIONS.find((a) => a.id === areaId)?.name ??
              `Регион №${areaId}`,
          )
          .join(", ");

  const hasRegionConflict =
    filterAreaLabel &&
    parsedRegion &&
    parsedRegion.trim().toLowerCase() !== filterAreaLabel.toLowerCase();

  const effectiveAreaLabel =
    Array.isArray(effectiveAreaIds) && effectiveAreaIds.length > 0
      ? effectiveAreaIds
          .map(
            (areaId) =>
              areaLabels?.get(areaId) ??
              FALLBACK_AREA_OPTIONS.find((a) => a.id === areaId)?.name ??
              `Регион №${areaId}`,
          )
          .join(", ")
      : null;

  const effectiveRegionText =
    effectiveAreaLabel && effectiveAreaSource === "panel"
      ? `Используется регион из панели: «${effectiveAreaLabel}»`
      : effectiveAreaLabel && effectiveAreaSource === "parsed_region"
        ? `Используется регион из запроса: «${effectiveAreaLabel}»`
        : effectiveAreaSource === "none"
          ? "Регион не указан"
          : null;
  if (items.length === 0 && !hasRegionConflict && !effectiveRegionText) return null;

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
      {effectiveRegionText && (
        <p className="text-xs text-muted-foreground">{effectiveRegionText}</p>
      )}
    </div>
  );
}
