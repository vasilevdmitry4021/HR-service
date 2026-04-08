import { describe, expect, it } from "vitest";

import {
  formatFavoriteSalaryAmount,
  formatResumeSalaryExpectations,
} from "./salary-format";

describe("formatResumeSalaryExpectations", () => {
  it("возвращает «Не указана» при отсутствии данных", () => {
    expect(formatResumeSalaryExpectations(null)).toBe("Не указана");
    expect(formatResumeSalaryExpectations(undefined)).toBe("Не указана");
    expect(formatResumeSalaryExpectations({})).toBe("Не указана");
  });

  it("форматирует amount", () => {
    expect(formatResumeSalaryExpectations({ amount: 150000, currency: "RUR" })).toBe(
      "150 000 RUR",
    );
  });

  it("форматирует диапазон from–to", () => {
    expect(
      formatResumeSalaryExpectations({
        from: 100000,
        to: 150000,
        currency: "RUR",
      }),
    ).toBe("100 000–150 000 RUR");
  });

  it("форматирует только от", () => {
    expect(
      formatResumeSalaryExpectations({ from: 200000, currency: "USD" }),
    ).toBe("от 200 000 USD");
  });
});

describe("formatFavoriteSalaryAmount", () => {
  it("возвращает «Не указана»", () => {
    expect(formatFavoriteSalaryAmount(null, "RUR")).toBe("Не указана");
  });

  it("форматирует сумму", () => {
    expect(formatFavoriteSalaryAmount(99000, "RUR")).toBe("99 000 RUR");
  });
});
