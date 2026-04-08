import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SearchInput } from "./SearchInput";

describe("SearchInput", () => {
  it("вызывает onSubmit по клику и по Ctrl+Enter", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    const onChange = vi.fn();

    render(
      <SearchInput
        value="Python"
        onChange={onChange}
        onSubmit={onSubmit}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Найти/i }));
    expect(onSubmit).toHaveBeenCalledTimes(1);

    const field = screen.getByRole("textbox", { name: /Поисковый запрос/i });
    await user.click(field);
    await user.keyboard("{Control>}{Enter}{/Control}");
    expect(onSubmit).toHaveBeenCalledTimes(2);
  });

  it("блокирует ввод и кнопку при loading", () => {
    render(
      <SearchInput
        value=""
        onChange={() => {}}
        onSubmit={() => {}}
        loading
      />,
    );
    expect(screen.getByRole("button")).toBeDisabled();
    expect(
      screen.getByRole("textbox", { name: /Поисковый запрос/i }),
    ).toBeDisabled();
  });
});
