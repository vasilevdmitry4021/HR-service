import { expect, test } from "@playwright/test";

const apiUrl = () =>
  process.env.PLAYWRIGHT_API_URL ?? "http://127.0.0.1:8000";

test.describe("критичные сценарии", () => {
  test("регистрация, поиск и избранное", async ({ page }) => {
    const email = `e2e_${Date.now()}@example.com`;
    const password = "e2e-pass-12";

    await page.goto("/register");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel(/Password/i).fill(password);
    await page.getByRole("button", { name: /Create account/i }).click();

    await expect(page).toHaveURL(/\/search/, { timeout: 60_000 });
    await expect(
      page.getByRole("button", { name: /Найти/i }),
    ).toBeVisible();

    await page.getByRole("button", { name: /Найти/i }).click();

    await expect(
      page.getByText(/Java Developer|Senior Python|разработчик/i).first(),
    ).toBeVisible({ timeout: 60_000 });

    const addFav = page
      .getByRole("button", { name: /Добавить в избранное/i })
      .first();
    await addFav.click();
    await expect(
      page.getByRole("button", { name: /Убрать из избранного/i }).first(),
    ).toBeVisible({ timeout: 15_000 });
  });

  test("вход существующего пользователя", async ({ page, context }) => {
    const email = `e2e_login_${Date.now()}@example.com`;
    const password = "e2e-pass-12";

    const reg = await context.request.post(
      `${apiUrl()}/api/v1/auth/register`,
      {
        data: { email, password },
        headers: { "Content-Type": "application/json" },
      },
    );
    expect(reg.ok()).toBeTruthy();

    await context.clearCookies();
    await page.goto("/");
    await page.evaluate(() => {
      localStorage.removeItem("hr-auth");
    });

    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel(/Password/i).fill(password);
    await page.getByRole("button", { name: /Sign in/i }).click();

    await expect(page).toHaveURL(/\/search/, { timeout: 60_000 });
  });
});
