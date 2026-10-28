import {test,expect} from '@playwright/test';
test.setTimeout(60000);
test('universal controls clear unsupported stale filters',async({page})=>{
 await page.addInitScript(()=>sessionStorage.setItem('allsewpattern.filters',JSON.stringify({audience:'men',is_new:true,is_knit:true,is_beginner:true,sort:'new_first'})));
 await page.goto('/');await expect(page.locator('.product-card').first()).toBeVisible();
 await expect(page.locator('.audiences button,.quick button,.catalog-sort')).toHaveCount(0);
 const stored=await page.evaluate(()=>JSON.parse(sessionStorage.getItem('allsewpattern.filters')||'{}'));
 expect(stored.audience).toBeNull();expect(stored.is_new).toBeNull();expect(stored.is_knit).toBeNull();expect(stored.sort).toBe('name');
 await page.getByRole('button',{name:/^Фильтры/}).click();
 await expect(page.locator('.filter-drawer').getByRole('combobox')).toHaveCount(2);
 await expect(page.locator('.filter-drawer').getByRole('switch')).toHaveCount(0);
});
test('alphabetical brands and category intersection have accurate counts',async({page})=>{
 await page.goto('/');await expect(page.locator('.product-card').first()).toBeVisible();
 await page.getByRole('button',{name:/^Фильтры/}).click();const drawer=page.locator('.filter-drawer');
 await drawer.getByRole('combobox',{name:'Все бренды'}).click();
 const names=await page.getByRole('option').allTextContents();
 expect(names).toEqual([...names].sort((a,b)=>a.localeCompare(b,'ru',{sensitivity:'base',numeric:true})));
 await page.getByRole('option',{name:'Grasser',exact:true}).click();
 await drawer.getByRole('combobox',{name:'Все категории'}).click();
 const response=page.waitForResponse(r=>r.url().includes('/api/products?')&&r.url().includes('source=grasser')&&new URL(r.url()).searchParams.get('category')==='Брюки и шорты');
 await page.getByRole('option',{name:'Брюки и шорты',exact:true}).click();
 const data=await(await response).json();expect(data.total).toBeGreaterThan(0);
 expect(data.items.every((p:{source:string;category:string})=>p.source==='grasser'&&p.category==='Брюки и шорты')).toBe(true);
 await expect(drawer.getByRole('button',{name:'Показать · '+data.total,exact:true})).toBeVisible();
 await page.screenshot({path:'test-results/common-filters.png'});
});
