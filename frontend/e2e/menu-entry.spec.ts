import {test,expect} from '@playwright/test';

test('Telegram manufacturer entry survives launch hash and allows returning to catalog',async({page})=>{
 await page.goto('/?section=suppliers#tgWebAppVersion=8.0&tgWebAppPlatform=ios');
 await expect(page.getByRole('heading',{name:'Производители выкроек'})).toBeVisible();
 await expect(page.locator('.supplier-card').first()).toBeVisible();
 expect(new URL(page.url()).searchParams.has('section')).toBe(false);
 await page.locator('.view-tabs').getByRole('link',{name:'Выкройки',exact:true}).click();
 await expect(page.locator('.product-card').first()).toBeVisible();
 await page.reload();
 await expect(page.locator('.product-card').first()).toBeVisible();
 await page.goto('/?section=catalog#/suppliers');
 await expect(page.locator('.product-card').first()).toBeVisible();
});

test('round up-arrow appears after scrolling and instantly returns to filters',async({page})=>{
 await page.goto('/?section=suppliers');
 await expect(page.locator('.supplier-card').first()).toBeVisible();
 const top=page.getByRole('button',{name:'Наверх',exact:true});
 await expect(top).toHaveCount(0);
 await page.evaluate(()=>window.scrollTo(0,1600));
 await expect(top).toBeVisible();
 await expect(top).toHaveText('');
 await expect(top).toHaveCSS('border-radius','50%');
 const bounds=await top.boundingBox();
 expect(bounds!.width).toBe(bounds!.height);
 await page.screenshot({path:'test-results/round-up-arrow.png'});
 await top.click();
 await expect.poll(()=>page.evaluate(()=>window.scrollY)).toBe(0);
 await expect(top).toHaveCount(0);
});
