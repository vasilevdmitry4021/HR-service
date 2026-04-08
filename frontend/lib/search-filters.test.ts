import { describe, expect, it } from "vitest";

import {
  emptySearchFilters,
  filtersFromApiPayload,
  filtersToApiPayload,
  filtersToReadableSummary,
} from "./search-filters";

describe("search-filters", () => {
  it("filtersFromApiPayload восстанавливает area и experience", () => {
    const s = filtersFromApiPayload({
      area: 3,
      experience: "between3And6",
      gender: "female",
    });
    expect(s.area).toBe(3);
    expect(s.experience).toBe("between3And6");
    expect(s.gender).toBe("female");
  });

  it("filtersToApiPayload отправляет только заданные поля (валюта по умолчанию — RUR)", () => {
    expect(filtersToApiPayload(emptySearchFilters())).toEqual({ currency: "RUR" });
    const p = filtersToApiPayload({
      ...emptySearchFilters(),
      area: 1,
      age_from: "25",
    });
    expect(p).toEqual({ area: 1, age_from: 25, currency: "RUR" });
  });

  describe("filtersToReadableSummary", () => {
    it("возвращает пустой массив для пустого state", () => {
      expect(filtersToReadableSummary(emptySearchFilters())).toEqual([]);
    });

    it("возвращает метку региона только для area", () => {
      const s = { ...emptySearchFilters(), area: 2 };
      expect(filtersToReadableSummary(s)).toEqual(["Санкт-Петербург"]);
    });

    it("возвращает комбинацию полей", () => {
      const s = {
        ...emptySearchFilters(),
        area: 2,
        experience: "between3And6",
        gender: "male",
      };
      expect(filtersToReadableSummary(s)).toEqual([
        "Санкт-Петербург",
        "3–6 лет",
        "Мужской",
      ]);
    });

    it("возвращает возраст от-до", () => {
      const s = {
        ...emptySearchFilters(),
        age_from: "25",
        age_to: "40",
      };
      expect(filtersToReadableSummary(s)).toEqual(["Возраст: 25–40"]);
    });

    it("возвращает зарплату от", () => {
      const s = {
        ...emptySearchFilters(),
        salary_from: "100000",
      };
      expect(filtersToReadableSummary(s)).toEqual(["Зарплата: от 100000"]);
    });

    it("для неизвестного id региона выводит номер", () => {
      const s = { ...emptySearchFilters(), area: 999_999 };
      expect(filtersToReadableSummary(s)).toEqual(["Регион №999999"]);
    });

    it("берёт подпись из переданной карты id→название", () => {
      const s = { ...emptySearchFilters(), area: 42 };
      const m = new Map<number, string>([[42, "Тестовый регион"]]);
      expect(filtersToReadableSummary(s, m)).toEqual(["Тестовый регион"]);
    });
  });
});
