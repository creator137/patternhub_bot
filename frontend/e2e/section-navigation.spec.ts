import {test,expect} from '@playwright/test';
test('supplier catalog selection clears unrelated filters',async({page})=>{
 await page.goto('/#/suppliers');await page.getByRole('textbox',{name:'Поиск поставщика'}).fill('VikiSews');
 const response=page.waitForResponse(r=>r.url().includes('/api/products?')&&r.url().includes('source=vikisews'));
 await page.locator('.supplier-card').getByRole('button',{name:/Выкройки/}).click();
 const result=await response;const params=new URL(result.url()).searchParams;
 for(const key of ['audience','is_new','is_sale','is_knit','is_beginner'])expect(params.has(key)).toBe(false);
 expect((await result.json()).items.every((p:{source:string})=>p.source==='vikisews')).toBe(true);
 await expect(page.locator('.product-card').first()).toBeVisible();
 await page.locator('.view-tabs').getByRole('link',{name:/Поставщики/}).click();
 await expect(page.locator('.supplier-card').first()).toBeVisible();
});
