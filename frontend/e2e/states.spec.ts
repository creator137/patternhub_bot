import {test,expect} from '@playwright/test';

test('failed images have a fallback, network error can be retried',async({page})=>{
  await page.route('**/api/products?**',route=>route.fulfill({status:503,body:'unavailable'}));
  await page.goto('/');
  await expect(page.getByText('Каталог временно недоступен')).toBeVisible();
  await page.unroute('**/api/products?**');
  await page.route('**/*',route=>route.request().resourceType()==='image'?route.abort():route.continue());
  await page.getByRole('button',{name:'Попробовать снова'}).click();
  await expect(page.locator('.product-card').first()).toBeVisible();
  await expect(page.locator('.photo-fallback').first()).toBeVisible();
  await page.screenshot({path:'test-results/image-fallback.png'});
});
