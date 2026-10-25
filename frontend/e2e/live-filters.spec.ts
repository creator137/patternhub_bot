import {test,expect} from '@playwright/test';

test('imported catalog has real results for every main section and quick filter',async({page})=>{
  await page.goto('/');
  await expect(page.locator('.product-card').first()).toBeVisible();
  for (const [label,key] of [['Женские','women'],['Мужские','men'],['Детские','kids'],['Унисекс','unisex']]) {
    const response=page.waitForResponse(r=>r.url().includes('/api/products?') && new URL(r.url()).searchParams.get('audience')===key);
    await page.locator('.audiences').getByRole('button',{name:new RegExp('^'+label)}).click();
    const data=await (await response).json();
    expect(data.total).toBeGreaterThan(0);
    expect(data.items.every((p:{audience:string})=>p.audience===key)).toBe(true);
    await expect(page.locator('.product-card').first()).toBeVisible();
  }
  const reset=page.waitForResponse(r=>r.url().includes('/api/products?')&&!new URL(r.url()).searchParams.has('audience'));
  await page.locator('.audiences').getByRole('button',{name:'Все выкройки'}).click();
  await reset;
  for(const [label,key] of [['Новинки','is_new'],['Скидки','is_sale'],['Бесплатные','is_free']]) {
    const response=page.waitForResponse(r=>r.url().includes('/api/products?')&&new URL(r.url()).searchParams.get(key)==='true');
    const button=page.locator('.quick').getByRole('button',{name:new RegExp(label)});
    await button.click();
    const data=await (await response).json();
    expect(data.total).toBeGreaterThan(0);
    expect(data.items.every((p:Record<string,unknown>)=>p[key]===true)).toBe(true);
    await expect(page.locator('.product-card').first()).toBeVisible();
    await page.screenshot({path:`test-results/filter-${key}.png`});
    const reset=page.waitForResponse(r=>r.url().includes('/api/products?')&&!new URL(r.url()).searchParams.has(key));
    await button.click();
    await reset;
  }
});
