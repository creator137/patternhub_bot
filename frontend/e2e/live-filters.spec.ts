import {test,expect} from '@playwright/test';
test('supplier directory has sorted links and distinguishes imported suppliers',async({page})=>{
 await page.goto('/#/suppliers');const cards=page.locator('.supplier-card');await expect(cards.first()).toBeVisible();
 expect(await cards.count()).toBeGreaterThanOrEqual(80);const names=await cards.locator('h3').allTextContents();
 expect(names).toEqual([...names].sort((a,b)=>a.localeCompare(b,'ru',{sensitivity:'base',numeric:true})));
 expect(await cards.locator('a.supplier-site').count()).toBe(names.length);
 expect(await cards.filter({has:page.locator('.supplier-products')}).count()).toBeGreaterThan(30);
 expect(await cards.filter({hasNot:page.locator('.supplier-products')}).count()).toBeGreaterThan(0);
 await expect(page.locator('a[href*="andrianova-pattern.ru"],a[href*="sew-garmentfactory"]')).toHaveCount(0);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:'test-results/suppliers-mobile.png'});
 await page.getByRole('textbox',{name:'Поиск поставщика'}).fill('marymake');
 await expect(cards).toHaveCount(1);await expect(cards.locator('a.supplier-site')).toHaveAttribute('href',/marymake/);
});
