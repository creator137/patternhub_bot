import {test,expect} from '@playwright/test';

test('submitting search dismisses focus without opening a product',async({page})=>{
 await page.goto('/');
 const search=page.getByRole('searchbox',{name:'Поиск выкроек'});
 await search.fill('Платье');
 await expect(search).toBeFocused();
 await search.press('Enter');
 await expect(search).not.toBeFocused();
 await expect(search).toHaveValue('Платье');
 await expect(page.locator('.product-card').first()).toBeVisible();
 expect(page.url()).not.toContain('/product/');
 await search.focus();
 await page.getByRole('button',{name:'Найти',exact:true}).click();
 await expect(search).not.toBeFocused();
 await search.focus();
 await page.locator('.catalog-heading').first().click();
 await expect(search).not.toBeFocused();
});

test('administrator uploads a logo and it persists after reload',async({page})=>{
 test.skip(!process.env.MINIAPP_DEV_KEY,'Isolated local backend required');
 await page.goto('/#/admin');
 await page.getByLabel('Локальный ключ').fill(process.env.MINIAPP_DEV_KEY!);
 await page.getByRole('button',{name:'Войти локально'}).click();
 await page.getByRole('button',{name:'Оформление',exact:true}).click();
 const png=await page.evaluate(async()=>{
  const canvas=document.createElement('canvas');canvas.width=canvas.height=900;
  canvas.getContext('2d')!.fillRect(0,0,900,900);
  return Array.from(new Uint8Array(await(await fetch(canvas.toDataURL('image/png'))).arrayBuffer()));
 });
 await page.getByLabel('Выбрать изображение').setInputFiles({name:'logo.png',mimeType:'image/png',buffer:Buffer.from(png)});
 await expect(page.getByRole('img',{name:'Предпросмотр аватарки'})).toHaveAttribute('src',/^blob:/);
 await page.getByRole('button',{name:'Сохранить аватарку'}).click();
 await expect(page.getByRole('status')).toHaveText('Сохранено');
 await expect(page.locator('.logo-image')).toHaveAttribute('src',/^\/api\/branding\/avatar\/[a-f0-9]+\.webp$/);
 const after=await page.locator('.logo-image').getAttribute('src');
 await page.reload();
 await expect(page.locator('.logo-image')).toHaveAttribute('src',after!);
 await expect.poll(()=>page.locator('.logo-image').evaluate((e:HTMLImageElement)=>e.complete&&e.naturalWidth===256)).toBe(true);
});
