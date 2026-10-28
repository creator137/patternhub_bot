import {test,expect} from '@playwright/test';
test.setTimeout(60000);
test('catalog controls remain available without the removed age cutoff and technical notice',async({page})=>{
 await page.addInitScript(()=>sessionStorage.setItem('allsewpattern.filters',JSON.stringify({is_new:true})));
 await page.goto('/');await expect(page.locator('.product-card').first()).toBeVisible();
 expect(await page.evaluate(()=>JSON.parse(sessionStorage.getItem('allsewpattern.filters')||'{}').is_new)).toBeNull();
 await expect(page.getByText(/аудитория пока не определена/)).toHaveCount(0);
 await expect(page.getByRole('button',{name:/За последние 60 дней/})).toHaveCount(0);
 await expect(page.locator('.audiences button')).toHaveCount(5);
 await expect(page.locator('.toolbar').getByRole('combobox',{name:'Сортировка'})).toBeVisible();
 await page.getByRole('button',{name:/^Фильтры/}).click();
 const drawer=page.locator('.filter-drawer');
 await expect(drawer.getByRole('combobox')).toHaveCount(4);
 await expect(drawer.getByRole('switch')).toHaveCount(4);
 for(const label of ['Скидки','Бесплатные и за 1 ₽','Для начинающих','Трикотаж'])
  await expect(drawer.locator('.toggle-row').filter({hasText:label}).getByRole('switch')).toBeVisible();
 await page.screenshot({path:'test-results/restored-filters.png'});
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
test('Grasser knit pants keep their filters when switching sort order',async({page})=>{
 await page.goto('/');await expect(page.locator('.product-card').first()).toBeVisible();
 await page.getByRole('button',{name:/^Фильтры/}).click();const drawer=page.locator('.filter-drawer');
 await drawer.getByRole('combobox',{name:'Все бренды'}).click();await page.getByRole('option',{name:'Grasser',exact:true}).click();
 await drawer.getByRole('combobox',{name:'Все категории'}).click();await page.getByRole('option',{name:'Брюки и шорты',exact:true}).click();
 const response=page.waitForResponse(r=>r.url().includes('/api/products?')&&r.url().includes('source=grasser')&&r.url().includes('is_knit=true'));
 await drawer.locator('.toggle-row').filter({hasText:'Трикотаж'}).getByRole('switch').click();
 const data=await(await response).json();expect(data.total).toBeGreaterThan(0);
 expect(data.items.every((p:{source:string;category:string;is_knit:boolean})=>p.source==='grasser'&&p.category==='Брюки и шорты'&&p.is_knit)).toBe(true);
 await drawer.getByRole('combobox',{name:'Сортировка',exact:true}).click();
 const sorted=page.waitForResponse(r=>r.url().includes('/api/products?')&&r.url().includes('sort=name')&&r.url().includes('is_knit=true'));
 await page.getByRole('option',{name:'По названию',exact:true}).click();
 expect((await(await sorted).json()).total).toBe(data.total);
});
