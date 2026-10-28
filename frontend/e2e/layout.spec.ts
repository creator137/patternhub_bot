import {test,expect} from '@playwright/test';

for(const width of [320,390,768,1440]) {
  test(`large source images and long product data stay contained at ${width}px`,async({page})=>{
    await page.setViewportSize({width,height:844});
    await page.goto('/',{waitUntil:'domcontentloaded'});
    await expect(page.locator('.product-card').first()).toBeVisible();
    const product=await page.evaluate(async()=> (await(await fetch('/api/products?limit=1')).json()).items[0]);
    const images=[[4000,8000],[8000,4000],[32,32]].map(([w,h])=>
      'data:image/svg+xml,'+encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}"><rect width="100%" height="100%" fill="#698653"/></svg>`));
    const item={...product,id:99999999,name:'ОченьДлинноеНазвание'.repeat(15),sizes:['Размер'.repeat(60)],
      image_url:images[0],image_urls:images,photo_urls:images,photo_thumbnails:images,image_count:3};
    await page.route(/\/api\/products\/99999999$/,route=>route.fulfill({json:item}));
    await page.goto('/#/product/99999999',{waitUntil:'domcontentloaded'});
    await expect(page.locator('.gallery-stage')).toBeVisible();
    for(let i=0;i<3;i++){
      await page.getByRole('button',{name:'Фото '+(i+1),exact:true}).click();
      const img=page.locator('.gallery-main img');
      await expect.poll(()=>img.evaluate((e:HTMLImageElement)=>e.complete&&e.naturalWidth>0)).toBe(true);
      const bounds=await page.locator('.gallery-stage').boundingBox();
      expect(bounds!.height).toBeLessThanOrEqual(501);
      expect(bounds!.width).toBeLessThanOrEqual(width);
      const image=await img.boundingBox();expect(image!.height).toBeLessThanOrEqual(bounds!.height+1);
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    }
    await expect(page.locator('.gallery-thumbs button').first()).toHaveCSS('height','80px');
    await page.screenshot({path:`test-results/layout-${width}.png`,fullPage:true});
  });
}
