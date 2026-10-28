import {test,expect} from '@playwright/test';

test('audience navigation clears previous quick filters instead of opening an empty intersection',async({page})=>{
  await page.goto('/');
  await expect(page.locator('.product-card').first()).toBeVisible();
  for(const [quick,audience,label] of [['Новинки','men','Мужские'],['Бесплатные','unisex','Унисекс']]){
    await page.locator('.quick').getByRole('button',{name:new RegExp(quick)}).click();
    await expect(page.getByRole('button',{name:new RegExp('^Убрать фильтр: '+quick)})).toBeVisible();
    const response=page.waitForResponse(r=>r.url().includes('/api/products?')&&new URL(r.url()).searchParams.get('audience')===audience);
    await page.locator('.audiences').getByRole('button',{name:new RegExp('^'+label)}).click();
    const result=await response;
    const params=new URL(result.url()).searchParams;
    expect(params.has('is_new')).toBe(false);
    expect(params.has('is_free')).toBe(false);
    expect((await result.json()).total).toBeGreaterThan(0);
    await expect(page.locator('.product-card').first()).toBeVisible();
    await expect(page.locator('.active-filters')).toHaveCount(0);
  }
});
