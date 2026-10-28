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
    expect(data.items.every((p:Record<string,unknown>)=>key==='is_free'
      ? p.is_free===true || (p.currency==='RUB' && Number(p.price)===1)
      : key==='is_new'
        ? !!p.source_published_at && Date.parse(String(p.source_published_at))>=Date.now()-60*86400000 && Date.parse(String(p.source_published_at))<=Date.now()
        : p[key]===true)).toBe(true);
    await expect(page.locator('.product-card').first()).toBeVisible();
    await expect.poll(()=>page.locator('.product-card img').first().evaluate((img:HTMLImageElement)=>img.complete&&img.naturalWidth>0),{timeout:20000}).toBe(true);
    if(key==='is_free') {
      const one=data.items.find((p:Record<string,unknown>)=>p.currency==='RUB'&&Number(p.price)===1);
      expect(one).toBeTruthy();
      const card=page.locator('.product-card').filter({has:page.locator(`a[href="#/product/${one.id}"]`)});
      await expect(card.locator('.price')).toContainText('1 ₽');
      await expect(card).not.toContainText('БЕСПЛАТНО');
    }
    await page.screenshot({path:`test-results/filter-${key}.png`});
    const reset=page.waitForResponse(r=>r.url().includes('/api/products?')&&!new URL(r.url()).searchParams.has(key));
    await button.click();
    await reset;
  }
});
