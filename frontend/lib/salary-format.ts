/** Зарплата из API резюме (HH: from/to/currency/gross; также amount). */

export type ResumeSalary = {
  amount?: number | null;
  from?: number | null;
  to?: number | null;
  currency?: string | null;
  gross?: boolean | null;
};

const MISSING = "Не указана";

function fmtNum(n: number): string {
  return n.toLocaleString("ru-RU");
}

export function formatResumeSalaryExpectations(
  salary: ResumeSalary | null | undefined,
): string {
  if (!salary || typeof salary !== "object") {
    return MISSING;
  }

  const cur =
    salary.currency != null && String(salary.currency).trim()
      ? String(salary.currency).trim()
      : "RUR";

  const amount = salary.amount;
  if (typeof amount === "number" && Number.isFinite(amount)) {
    let s = `${fmtNum(amount)} ${cur}`;
    if (salary.gross === true) {
      s += " (до вычета налогов)";
    }
    return s;
  }

  const from = salary.from;
  const to = salary.to;
  const hasFrom = typeof from === "number" && Number.isFinite(from);
  const hasTo = typeof to === "number" && Number.isFinite(to);

  if (!hasFrom && !hasTo) {
    return MISSING;
  }

  let part: string;
  if (hasFrom && hasTo) {
    part =
      from === to
        ? `${fmtNum(from)} ${cur}`
        : `${fmtNum(from)}–${fmtNum(to)} ${cur}`;
  } else if (hasFrom) {
    part = `от ${fmtNum(from)} ${cur}`;
  } else {
    part = `до ${fmtNum(to!)} ${cur}`;
  }
  if (salary.gross === true) {
    part += " (до вычета налогов)";
  }
  return part;
}

export function formatFavoriteSalaryAmount(
  amount: number | null | undefined,
  currency: string | null | undefined,
): string {
  if (amount == null || !Number.isFinite(amount)) {
    return MISSING;
  }
  const cur =
    currency != null && String(currency).trim()
      ? String(currency).trim()
      : "RUR";
  return `${fmtNum(amount)} ${cur}`;
}
