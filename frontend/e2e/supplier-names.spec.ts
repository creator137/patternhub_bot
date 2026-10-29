import {test,expect} from '@playwright/test';

test('administrator renames a supplier across directory, filters and cards',async({page})=>{
 test.skip(!process.env.MINIAPP_DEV_KEY,'Isolated local backend required');
 const key=process.env.MINIAPP_DEV_KEY!;
 const alias='Вики выкройки';
 await page.goto('/#/admin');
 await page.getByLabel('Локальный ключ').fill(key);
 await page.getByRole('button',{name:'Войти локально'}).click();
 const original=page.locator('article.panel').filter({has:page.getByRole('heading',{name:'VikiSews',exact:true})});
 await expect(original).toBeVisible();
 await original.getByRole('button',{name:'Изменить название'}).click();
 await original.getByLabel('Название производителя').fill('Не сохранять');
 await original.getByRole('button',{name:'Отмена',exact:true}).click();
 await expect(original.getByRole('heading',{name:'VikiSews',exact:true})).toBeVisible();
 try {
  await original.getByRole('button',{name:'Изменить название'}).click();
  await page.setViewportSize({width:320,height:844});
  await original.getByLabel('Название производителя').fill('Производитель'.repeat(11));
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await original.getByLabel('Название производителя').fill(alias);
  await original.getByRole('button',{name:'Сохранить название'}).click();
  await expect(page.getByRole('status')).toHaveText('Сохранено');
  await expect(page.getByRole('heading',{name:alias,exact:true})).toBeVisible();
  await page.goto('/#/suppliers');
  const supplier=page.locator('.supplier-card').filter({has:page.getByRole('heading',{name:alias,exact:true})});
  await expect(supplier).toBeVisible();
  await supplier.getByRole('button',{name:/Выкройки/}).click();
  await expect(page.locator('.product-card .brand').first()).toHaveText(alias);
  await page.getByRole('button',{name:/^Фильтры/}).click();
  await expect(page.locator('.filter-drawer').getByRole('combobox',{name:'Все бренды'})).toHaveText(alias);
  await page.reload();
  await expect(page.locator('.product-card .brand').first()).toHaveText(alias);
  const data=await(await page.request.get('/api/products?source=vikisews')).json();
  expect(data.items.every((p:{source:string;brand:string})=>p.source==='vikisews'&&p.brand===alias)).toBe(true);
  await page.screenshot({path:'test-results/supplier-name-mobile.png',fullPage:true});
 } finally {
  const response=await page.request.patch('/api/admin/sources/vikisews',{headers:{'X-Dev-Key':key},data:{display_name:'VikiSews'}});
  expect(response.ok()).toBe(true);
 }
});
