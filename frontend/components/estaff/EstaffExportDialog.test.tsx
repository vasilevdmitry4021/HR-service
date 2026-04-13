import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EstaffExportDialog } from "./EstaffExportDialog";

const mockFetchEstaffVacancies = vi.fn();
const mockPostEstaffExport = vi.fn();
const mockPostEstaffUserCheck = vi.fn();

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  ESTAFF_LAST_VACANCY_STORAGE_KEY: "hr_service_estaff_last_vacancy_id",
  ESTAFF_LAST_USER_LOGIN_STORAGE_KEY: "hr_service_estaff_last_user_login",
  estaffLlmAnalysisHasPayload: () => false,
  fetchEstaffVacancies: (...args: unknown[]) => mockFetchEstaffVacancies(...args),
  postEstaffExport: (...args: unknown[]) => mockPostEstaffExport(...args),
  postEstaffUserCheck: (...args: unknown[]) => mockPostEstaffUserCheck(...args),
  sanitizeApiErrorMessage: (msg: string | null | undefined) => msg ?? "Ошибка",
}));

describe("EstaffExportDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    mockFetchEstaffVacancies.mockResolvedValue({
      items: [{ id: "vac-1", title: "Python Developer", subtitle: null }],
    });
    mockPostEstaffExport.mockResolvedValue({ results: [] });
  });

  it("блокирует выгрузку до успешной проверки логина и проверяет через debounce", async () => {
    mockPostEstaffUserCheck.mockResolvedValue({
      valid: true,
      login: "hr.user",
      user_name: "HR User",
    });
    const user = userEvent.setup();

    render(
      <EstaffExportDialog
        open
        onOpenChange={() => undefined}
        resumeIds={["resume-1"]}
      />,
    );

    const exportButton = await screen.findByRole("button", {
      name: /Выгрузить в e-staff/i,
    });
    expect(exportButton).toBeDisabled();

    await user.click(await screen.findByRole("option", { name: /Python Developer/i }));
    expect(exportButton).toBeDisabled();

    await user.type(screen.getByLabelText(/Логин e-staff/i), "hr.user");
    expect(exportButton).toBeDisabled();

    expect(mockPostEstaffUserCheck).not.toHaveBeenCalled();

    await new Promise((resolve) => setTimeout(resolve, 5100));
    await waitFor(() => {
      expect(mockPostEstaffUserCheck).toHaveBeenCalledWith("hr.user");
    });
    await waitFor(() => {
      expect(exportButton).toBeEnabled();
    });

    expect(
      window.localStorage.getItem("hr_service_estaff_last_user_login"),
    ).toBe("hr.user");
  }, 15000);

  it("сбрасывает валидность после изменения логина", async () => {
    mockPostEstaffUserCheck
      .mockResolvedValueOnce({ valid: true, login: "hr.user", user_name: null })
      .mockResolvedValueOnce({ valid: true, login: "hr.user.2", user_name: null });
    const user = userEvent.setup();

    render(
      <EstaffExportDialog
        open
        onOpenChange={() => undefined}
        resumeIds={["resume-1"]}
      />,
    );

    await user.click(await screen.findByRole("option", { name: /Python Developer/i }));
    const loginInput = screen.getByLabelText(/Логин e-staff/i);
    const exportButton = screen.getByRole("button", { name: /Выгрузить в e-staff/i });

    await user.type(loginInput, "hr.user");
    await new Promise((resolve) => setTimeout(resolve, 5100));
    await waitFor(() => expect(exportButton).toBeEnabled());

    await user.clear(loginInput);
    await user.type(loginInput, "hr.user.2");
    expect(exportButton).toBeDisabled();

    await new Promise((resolve) => setTimeout(resolve, 5100));
    await waitFor(() =>
      expect(mockPostEstaffUserCheck).toHaveBeenLastCalledWith("hr.user.2"),
    );
    await waitFor(() => expect(exportButton).toBeEnabled());
  }, 20000);

  it("автоподставляет логин из localStorage и сразу запускает проверку", async () => {
    window.localStorage.setItem("hr_service_estaff_last_user_login", "cached.hr");
    mockPostEstaffUserCheck.mockResolvedValue({
      valid: true,
      login: "cached.hr",
      user_name: "Cached User",
    });

    render(
      <EstaffExportDialog
        open
        onOpenChange={() => undefined}
        resumeIds={["resume-1"]}
      />,
    );

    await waitFor(() => {
      expect(screen.getByLabelText(/Логин e-staff/i)).toHaveValue("cached.hr");
    });
    await waitFor(() => {
      expect(mockPostEstaffUserCheck).toHaveBeenCalledWith("cached.hr");
    });
  });

  it("при вставке логина запускает проверку сразу, без ожидания debounce", async () => {
    mockPostEstaffUserCheck.mockResolvedValue({
      valid: true,
      login: "paste.hr",
      user_name: "Paste User",
    });
    const user = userEvent.setup();

    render(
      <EstaffExportDialog
        open
        onOpenChange={() => undefined}
        resumeIds={["resume-1"]}
      />,
    );

    const loginInput = await screen.findByLabelText(/Логин e-staff/i);
    await user.click(loginInput);
    await user.paste("paste.hr");

    await waitFor(() => {
      expect(mockPostEstaffUserCheck).toHaveBeenCalledWith("paste.hr");
    });
  });
});
