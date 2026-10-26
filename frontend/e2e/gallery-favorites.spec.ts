import { test, expect } from '@playwright/test';

test('favorites survive reload; catalog remains compact and returns from detail', async ({ page }) => {
  await page.goto('/');
  const first = page.locator('.product-card').first();
  await expect(first).toBeVisible();
  expect(await first.evaluate(el => el.getBoundingClientRect().top)).toBeLessThan(650);
  await first.getByRole('button', { name: /^Сохранить:/ }).click();
  await page.getByRole('button', { name: /^Избранное/ }).click();
  await expect(page.locator('.product-card')).toHaveCount(1);
  await page.reload();
  await page.getByRole('button', { name: /^Избранное/ }).click();
  await expect(page.locator('.product-card')).toHaveCount(1);
  await page.locator('.product-open').first().click();
  await expect(page.locator('.detail')).toBeVisible();
  await page.getByRole('button', { name: 'К выкройкам' }).click();
  await expect(page.locator('.product-card')).toHaveCount(1);
  await page.screenshot({ path: 'test-results/favorites-mobile.png' });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('real Rika gallery: thumbnails, next/back, lightbox and zoom', async ({ page, request }) => {
  const response = await request.get('/api/products?search=' + encodeURIComponent('Берет Рика'));
  const product = (await response.json()).items[0];
  test.skip(!product || product.image_count < 2, 'Run offline gallery enrichment for Rika first');
  await page.goto('/#/product/' + product.id);
  const stage = page.locator('.gallery-stage');
  await expect(page.locator('.gallery-counter')).toHaveText('1 / ' + product.image_count);
  await stage.getByRole('button', { name: 'Следующее фото', exact: true }).click();
  await expect(page.locator('.gallery-counter')).toHaveText('2 / ' + product.image_count);
  await stage.getByRole('button', { name: 'Предыдущее фото', exact: true }).click();
  await expect(page.locator('.gallery-counter')).toHaveText('1 / ' + product.image_count);
  await page.getByRole('button', { name: 'Фото 3', exact: true }).click();
  await expect(page.locator('.gallery-counter')).toHaveText('3 / ' + product.image_count);
  await stage.getByRole('button', { name: /^Увеличить фото:/ }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: 'Увеличить фото', exact: true }).click();
  await expect(page.locator('.lightbox')).toHaveClass(/zoomed/);
  await expect.poll(() => page.locator('.lightbox img').evaluate((el: HTMLImageElement) =>
    el.complete && el.naturalWidth > 0)).toBe(true);
  await page.screenshot({ path: 'test-results/rika-lightbox-mobile.png' });
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({ path: 'test-results/rika-gallery-desktop.png' });
});
