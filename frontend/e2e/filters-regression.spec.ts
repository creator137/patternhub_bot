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
  await page.getByRole('button', { name: /^За последние 60 дней/ }).click();
  await expect(page.getByRole('button', { name: 'Весь каталог, сначала новинки' })).toBeVisible();
  const result = page.waitForResponse(r => r.url().includes('/api/products?') && r.url().includes('sort=new_first'));
  await page.getByRole('button', { name: 'Весь каталог, сначала новинки' }).click();
  const data = await (await result).json();
  expect(data.total).toBeGreaterThan(1000);
  expect(data.items.every((p: {source_recency_rank:number|null}) => p.source_recency_rank !== null)).toBe(true);
  await expect(page.getByRole('button', { name: 'Весь каталог, сначала новинки' })).not.toBeVisible();
});

test('Grasser knit pants keep every match when switching from names to newest first', async ({ page }) => {
  await page.goto('/', { waitUntil:'domcontentloaded' });
  await expect(page.locator('.product-card').first()).toBeVisible();
  await expect(page.locator('.toolbar').getByRole('combobox', {name:'Сортировка'})).toBeVisible();
  await page.getByRole('button', {name:/^Фильтры/}).click();
  const drawer = page.locator('.filter-drawer');
  await drawer.getByRole('combobox', {name:'Все бренды'}).click();
  await page.getByRole('option', {name:'Grasser', exact:true}).click();
  await drawer.getByRole('combobox', {name:'Все категории'}).click();
  await page.getByRole('option', {name:'Брюки и шорты', exact:true}).click();
  let response = page.waitForResponse(r => r.url().includes('/api/products?') &&
    r.url().includes('source=grasser') && r.url().includes('is_knit=true'));
  await drawer.locator('.toggle-row').filter({hasText:'Трикотаж'}).getByRole('switch').click();
  const initial = await (await response).json();
  expect(initial.total).toBeGreaterThan(1);
  await drawer.getByRole('combobox', {name:'Сортировка', exact:true}).click();
  response = page.waitForResponse(r => r.url().includes('/api/products?') && r.url().includes('sort=name'));
  await page.getByRole('option', {name:'По названию', exact:true}).click();
  expect((await (await response).json()).total).toBe(initial.total);
  await drawer.getByRole('combobox', {name:'Сортировка', exact:true}).click();
  response = page.waitForResponse(r => r.url().includes('/api/products?') && r.url().includes('sort=new_first'));
  await page.getByRole('option', {name:'От новых к старым', exact:true}).click();
  const sortedResponse = await response;
  const sorted = await sortedResponse.json();
  expect(new URL(sortedResponse.url()).searchParams.has('is_new')).toBe(false);
  expect(sorted.total).toBe(initial.total);
  expect(sorted.items.every((p:{source:string;category:string;is_knit:boolean;source_recency_rank:number|null}) =>
    p.source==='grasser' && p.category==='Брюки и шорты' && p.is_knit && p.source_recency_rank!==null)).toBe(true);
  const ranks = sorted.items.map((p:{source_recency_rank:number}) => p.source_recency_rank);
  expect(ranks).toEqual([...ranks].sort((a,b)=>a-b));
  await drawer.getByRole('button', {name:/^Показать/}).click();
  await expect(drawer).toBeHidden();
  await expect(page.locator('.product-card').first()).toBeVisible();
  await expect.poll(()=>page.locator('.product-card img').first().evaluate((img:HTMLImageElement)=>img.complete&&img.naturalWidth>0),{timeout:20000}).toBe(true);
  await page.screenshot({path:'test-results/grasser-knit-pants-newest.png'});
});

test('newest-first covers the entire available catalog of each of five brands', async ({ page }) => {
  await page.goto('/', {waitUntil:'domcontentloaded'});
  const browse = (params:Record<string,string>) => page.evaluate(async params => {
    const response = await fetch('/api/products?'+new URLSearchParams(params), {signal:AbortSignal.timeout(15000)});
    if (!response.ok) throw new Error('Catalog HTTP '+response.status);
    return response.json();
  }, params);
  for (const source of ['grasser','helpersew','vikisews','studio_yusupova','sewitnow']) {
    const named = await browse({source,sort:'name',limit:'60'});
    const ordered = await browse({source,sort:'new_first',limit:'60'});
    expect(ordered.total).toBe(named.total);
    expect(ordered.total).toBeGreaterThan(60);
    expect(ordered.items.every((p:{source_recency_rank:number|null}) => p.source_recency_rank!==null)).toBe(true);
    const ranks = ordered.items.map((p:{source_recency_rank:number}) => p.source_recency_rank);
    expect(ranks).toEqual([...ranks].sort((a,b)=>a-b));
  }
});
