import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { emptySearchFilters, FALLBACK_AREA_OPTIONS } from "@/lib/search-filters";

import { FilterPanel } from "./FilterPanel";

describe("FilterPanel", () => {
  it("меняет регион и вызывает onChange", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const value = emptySearchFilters();

    render(
      <FilterPanel
        value={value}
        onChange={onChange}
        areas={FALLBACK_AREA_OPTIONS}
        areasLoading={false}
      />,
    );

    await user.click(screen.getByLabelText(/^Регион$/i));
    await user.click(screen.getByRole("button", { name: /^Санкт-Петербург$/i }));
    expect(onChange).toHaveBeenCalled();
    const last = onChange.mock.calls.at(-1)?.[0];
    expect(last?.area).toEqual([2]);
  });

  it("сбрасывает фильтры по кнопке", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const value = { ...emptySearchFilters(), area: [1] };

    render(
      <FilterPanel
        value={value}
        onChange={onChange}
        areas={FALLBACK_AREA_OPTIONS}
        areasLoading={false}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Сбросить фильтры/i }));
    expect(onChange).toHaveBeenCalled();
    const reset = onChange.mock.calls.at(-1)?.[0];
    expect(reset?.area).toEqual([]);
  });
});
