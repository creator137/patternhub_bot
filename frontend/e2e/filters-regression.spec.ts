import { test, expect } from '@playwright/test';
test.setTimeout(60000);

test('VikiSews beginner filter returns matching cards and an accurate drawer count', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.product-card').first()).toBeVisible();
  await page.getByRole('button', { name: /^Фильтры/ }).click();
  const drawer = page.locator('.filter-drawer');
  await drawer.getByRole('combobox', { name: 'Все бренды' }).click();
  await page.getByRole('option', { name: 'VikiSews', exact: true }).click();
  const resultPromise = page.waitForResponse(r => r.url().includes('/api/products?') &&
    r.url().includes('source=vikisews') && r.url().includes('is_beginner=true'));
  await drawer.locator('.toggle-row').filter({ hasText: 'Для начинающих' }).getByRole('switch').click();
  const data = await (await resultPromise).json();
  expect(data.total).toBeGreaterThan(0);
  expect(data.items.every((p: {source:string;is_beginner:boolean}) => p.source === 'vikisews' && p.is_beginner)).toBe(true);
  await expect(drawer.getByRole('button', { name: 'Показать · ' + data.total, exact: true })).toBeVisible();
  await page.screenshot({ path: 'test-results/viki-beginner-filter.png' });
  await drawer.getByRole('button', { name: /^Показать/ }).click();
  await expect(page.locator('.product-card').first()).toBeVisible();
});

test('new-first sorting keeps the full catalog instead of restricting it to new badges', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.product-card').first()).toBeVisible();
  await page.getByRole('button', { name: /^Новинки/ }).click();
  await expect(page.getByRole('button', { name: 'Весь каталог, сначала новинки' })).toBeVisible();
  const result = page.waitForResponse(r => r.url().includes('/api/products?') && r.url().includes('sort=new_first'));
  await page.getByRole('button', { name: 'Весь каталог, сначала новинки' }).click();
  const data = await (await result).json();
  expect(data.total).toBeGreaterThan(1000);
  expect(data.items[0].is_new).toBe(true);
  await expect(page.getByRole('button', { name: 'Весь каталог, сначала новинки' })).not.toBeVisible();
});
