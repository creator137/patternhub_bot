import {test,expect} from '@playwright/test';

test('verified Telegram visits and shop clicks appear in administrator statistics',async({page})=>{
 test.skip(!process.env.ANALYTICS_TEST_INIT_DATA,'Isolated signed test session required');
 await page.route('https://telegram.org/js/telegram-web-app.js',route=>route.fulfill({contentType:'text/javascript',body:`window.Telegram={WebApp:{initData:${JSON.stringify(process.env.ANALYTICS_TEST_INIT_DATA)},ready(){},expand(){},onEvent(){},offEvent(){},BackButton:{show(){},hide(){},onClick(){},offClick(){}}}};`}));
 let lostAcknowledgement=false;
 await page.route('**/api/events',async route=>{
  if(route.request().postDataJSON()?.kind==='outbound' && !lostAcknowledgement) {
   lostAcknowledgement=true;
   await route.fetch(); // The event was saved; its acknowledgement was lost.
   await route.fulfill({status:503,body:'Retry'});
  } else await route.continue();
 });
 await page.goto('/');
 await expect(page.locator('.product-card').first()).toBeVisible();
 await page.locator('.product-card').first().click();
 const event=page.waitForResponse(r=>r.url().endsWith('/api/events')&&r.request().postDataJSON()?.kind==='outbound'&&r.status()===200);
 await page.getByRole('link',{name:'Перейти в магазин'}).click();
 expect((await event).status()).toBe(200);
 await page.goto('/#/suppliers');
 const supplierEvent=page.waitForResponse(r=>r.url().endsWith('/api/events')&&r.request().postDataJSON()?.kind==='outbound'&&r.status()===200);
 await page.locator('.supplier-site').first().click();
 expect((await supplierEvent).status()).toBe(200);
 await page.goto('/#/admin');
 await page.getByRole('button',{name:'Статистика',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Статистика приложения'})).toBeVisible();
 await expect(page.locator('.analytics .admin-grid .panel').nth(0)).toHaveText(/1\s*Уникальные пользователи/);
 await expect(page.locator('.analytics .admin-grid .panel').nth(2)).toHaveText(/2\s*Переходы на сайты/);
 await expect(page.locator('.analytics-table').first()).toContainText('Grasser');
 await page.getByLabel('Период статистики').selectOption('7');
 await expect(page.locator('.analytics-table').nth(1).locator('tbody tr')).toHaveCount(7);
 expect(await page.locator('.analytics').evaluate(el=>el.scrollWidth<=window.innerWidth)).toBe(true);
});
