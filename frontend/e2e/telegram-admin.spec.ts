import { createHmac } from "node:crypto";
import { test, expect } from "@playwright/test";

// Run only against an isolated database and a backend with this test bot token.
test.skip(!process.env.E2E_BOT_TOKEN, "Isolated Telegram auth test requires E2E_BOT_TOKEN");

for (const [index, username] of ["shanniwaby", "tatiana_svetlic"].entries()) {
  test(`signed Telegram admin: ${username}`, async ({ page }) => {
    const values: Record<string, string> = {
      auth_date: String(Math.floor(Date.now() / 1000)),
      user: JSON.stringify({ id: 910001 + index, username }),
    };
    const key = createHmac("sha256", "WebAppData")
      .update(process.env.E2E_BOT_TOKEN!).digest();
    values.hash = createHmac("sha256", key)
      .update(Object.keys(values).sort().map(k => `${k}=${values[k]}`).join("\n"))
      .digest("hex");
    const initData = new URLSearchParams(values).toString();
    await page.route("https://telegram.org/js/telegram-web-app.js*", route =>
      route.fulfill({ contentType: "application/javascript", body: "" }));
    await page.addInitScript((initData) => {
      const noop = () => {};
      Object.assign(window, { Telegram: { WebApp: {
        initData, colorScheme: "light", ready: noop, expand: noop,
        onEvent: noop, offEvent: noop,
        BackButton: { show: noop, hide: noop, onClick: noop, offClick: noop },
      } } });
    }, initData);
    await page.goto("/");
    await expect(page.locator(".product-card").first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Управление", exact: true })).toBeVisible();
    await page.screenshot({ path: `test-results/telegram-${username}-catalog.png` });
    await page.getByRole("button", { name: "Управление", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Управление", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Фильтры и меню", exact: true })).toBeVisible();
    await page.screenshot({ path: `test-results/telegram-${username}-admin.png` });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.screenshot({ path: `test-results/telegram-${username}-admin-desktop.png` });
  });
}
