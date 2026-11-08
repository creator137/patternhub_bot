import {test,expect} from '@playwright/test';

test('subscription: mobile paywall, explicit trial and checkout consent',async({page})=>{
  const errors:string[]=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('https://telegram.org/js/telegram-web-app.js*',route=>route.fulfill({body:''}));
  await page.addInitScript(()=>{
    const noop=()=>{};
    Object.assign(window,{Telegram:{WebApp:{initData:'fixture',colorScheme:'light',ready:noop,expand:noop,onEvent:noop,offEvent:noop,openLink:noop,BackButton:{show:noop,hide:noop,onClick:noop,offClick:noop}}}});
  });
  let trial=false;
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    let data:unknown={};let status=200;
    if(path==='/api/subscription/plan') data={enabled:true,price_kopecks:29900,terms_url:'https://example.com/terms',support_url:'https://t.me/help',payments_ready:true,test:true};
    else if(path==='/api/subscription/trial'){trial=true;data={};}
    else if(path==='/api/subscription') data={trial_available:!trial,has_access:trial,state:trial?'trial':'new',trial_end:trial?1794000000:null,access_until:trial?1794000000:null};
    else if(path==='/api/subscription/payments')data=[];
    else if(path==='/api/meta')data={ui:{filters:[],menu:[]},common_filters:[],categories:[],brands:[],category_options:[],supplier_count:0,coverage:{counts:{},unknown_audience:0,total:0},local_login:false};
    else if(path==='/api/products'){data={items:[],total:0};if(!trial){status=402;data={detail:'Подписка необходима'};}}
    else if(path==='/api/admin/session'){status=403;}
    else if(path==='/api/favorites')data={ids:[]};
    await route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.goto('/#/subscription');
  await expect(page.getByRole('heading',{name:'Все выкройки — в одном каталоге'})).toBeVisible();
  const pay=page.getByRole('button',{name:/Оплатить 30 дней/});
  await expect(pay).toBeDisabled();
  await page.getByRole('checkbox').check();
  await expect(pay).toBeEnabled();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:'test-results/subscription-mobile.png',fullPage:true});
  await page.getByRole('button',{name:'Попробовать 7 дней бесплатно'}).click();
  await expect(page.getByText(/Пробный доступ до/)).toBeVisible();
  await expect(page.getByRole('button',{name:'Попробовать 7 дней бесплатно'})).toHaveCount(0);
  await page.emulateMedia({colorScheme:'dark'});
  expect(errors).toEqual([]);
});
