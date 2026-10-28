import { test, expect } from "@playwright/test";
test.setTimeout(60000);

test("real catalog: mobile grid, filters, detail, back, fallback and dark theme", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(page.locator(".product-card").first()).toBeVisible();
  await expect(page.locator(".product-card")).toHaveCount(24);
  expect(
    await page
      .locator(".product-grid")
      .evaluate(
        (el) => getComputedStyle(el).gridTemplateColumns.split(" ").length,
      ),
  ).toBe(2);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await expect
    .poll(
      () =>
        page
          .locator(".product-card img")
          .first()
          .evaluate(
            (img: HTMLImageElement) => img.complete && img.naturalWidth > 0,
          ),
      { timeout: 20000 },
    )
    .toBe(true);
  await page.screenshot({ path: "test-results/catalog-mobile.png" });
  const nextPage = page.waitForResponse(r => r.url().includes('/api/products?') && new URL(r.url()).searchParams.get('offset') === '24');
  await page.getByRole("button", { name: "Показать ещё", exact: true }).click();
  expect((await nextPage).ok()).toBe(true);
  await expect(page.locator(".product-card")).toHaveCount(48);
  await page.getByRole("button", { name: "Фильтры", exact: true }).click();
  await expect(page.locator(".filter-drawer")).toBeVisible();
  await expect(
    page.locator(".filter-drawer .p-drawer-footer"),
  ).toBeInViewport();
  await page
    .locator(".filter-drawer")
    .getByRole("combobox", { name: "Все категории" })
    .click();
  await expect(page.getByRole("listbox")).toBeVisible();
  await expect(page.locator(".p-select-overlay")).toHaveCSS("opacity", "1");
  await page.screenshot({ path: "test-results/select-open-mobile.png" });
  await page.getByRole("option", { name: "Аксессуары", exact: true }).click();
  await expect(
    page.locator(".filter-drawer .catalog-select").first(),
  ).toContainText("Аксессуары");
  await page.locator(".filter-drawer .p-select-clear-icon").first().click();
  await page.locator(".p-drawer-title").click();
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await page.emulateMedia({ colorScheme: "dark" });
  await page
    .locator(".filter-drawer")
    .getByRole("combobox", { name: "Все бренды" })
    .focus();
  await page.keyboard.press("Space");
  await expect(page.getByRole("listbox")).toBeVisible();
  await expect(page.locator(".p-select-overlay")).toHaveCSS("opacity", "1");
  await page.screenshot({ path: "test-results/select-dark-mobile.png" });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await page.emulateMedia({ colorScheme: "light" });
  await page.screenshot({ path: "test-results/filters-mobile.png" });
  await page.locator(".p-drawer-close-button").click();
  await page
    .getByRole("textbox", { name: "Поиск выкроек" })
    .fill("zz-not-found-123");
  await expect(page.getByText("Пока ничего не нашлось")).toBeVisible();
  await page
    .getByRole("button", { name: "Сбросить фильтры", exact: true })
    .click();
  await expect(page.locator(".product-card").first()).toBeVisible();
  const title = await page.locator(".product-card h3").first().textContent();
  await page.locator(".product-card").first().click();
  await expect(page.locator(".detail h1")).toHaveText(title!);
  await expect(
    page.getByRole("link", { name: "Перейти в магазин" }),
  ).toHaveAttribute("href", /^https?:\/\//);
  await page.screenshot({
    path: "test-results/detail-mobile.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "К выкройкам" }).click();
  await expect(page.locator(".product-card").first()).toBeVisible();
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveClass("dark");
  await page.screenshot({ path: "test-results/catalog-dark.png" });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.emulateMedia({ colorScheme: "light" });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: "test-results/catalog-desktop.png" });
  expect(errors).toEqual([]);
});

test("admin: local login, source toggle, settings and product editing", async ({
  page,
}) => {
  test.skip(
    !process.env.MINIAPP_DEV_KEY,
    "Explicit local-only test key required",
  );
  await page.goto("/#/admin");
  await page.getByLabel("Локальный ключ").fill(process.env.MINIAPP_DEV_KEY!);
  await page.getByRole("button", { name: "Войти локально" }).click();
  await expect(
    page.getByRole("heading", { name: "Управление", exact: true }),
  ).toBeVisible();
  await page.getByRole("switch", { name: "Включить VikiSews" }).click();
  await expect(
    page.getByRole("switch", { name: "Включить VikiSews" }),
  ).not.toBeChecked();
  await page.getByRole("switch", { name: "Включить VikiSews" }).click();
  await expect(
    page.getByRole("switch", { name: "Включить VikiSews" }),
  ).toBeChecked();
  await page.screenshot({
    path: "test-results/admin-sources.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Фильтры каталога" }).click();
  await page.getByRole("switch", { name: "Категория", exact: true }).click();
  await page.getByRole("button", { name: "Сохранить настройки" }).click();
  await expect(page.getByRole("status")).toHaveText("Сохранено");
  await page.getByRole("button", { name: "В каталог", exact: false }).click();
  await expect(
    page.locator(".categories"),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Управление", exact: true }).click();
  await page.getByRole("button", { name: "Фильтры каталога" }).click();
  await page.getByRole("switch", { name: "Категория", exact: true }).click();
  await page.getByRole("button", { name: "Сохранить настройки" }).click();
  await page.getByRole("button", { name: "Товары", exact: true }).click();
  await page.locator(".admin-product").first().click();
  await expect(
    page.getByRole("button", { name: "Сохранить товар" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Сохранить товар" }).click();
  await expect(page.getByRole("status")).toHaveText("Сохранено");
});
