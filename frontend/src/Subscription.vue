<script setup lang="ts">
import {onMounted, ref} from 'vue';
import Button from 'primevue/button';
import Checkbox from 'primevue/checkbox';
import {api,tg} from './api';
import {plan,access,refreshSubscription,rub,until} from './subscription';
const emit=defineEmits<{changed:[]}>();
const busy=ref(false), error=ref(''), accepted=ref(false);
type Payment={id:string;amount:number;test:boolean;created:number;status:string;checkout_url:string|null;refunded:number};
const payments=ref<Payment[]>([]);
async function refresh() {
  await refreshSubscription();
  if(tg?.initData) payments.value=await api('/subscription/payments');
}
async function action(fn:()=>Promise<void>) {
  busy.value=true;error.value='';
  try{await fn();await refresh();emit('changed');}catch(e){error.value=(e as Error).message;}
  finally{busy.value=false;}
}
function openCheckout(url:string){if(tg?.openLink)tg.openLink(url);else window.location.assign(url);}
async function pay(){await action(async()=>{
  const result=await api<Payment>('/subscription/payments','POST',{
    accepted_terms:accepted.value,price_kopecks:plan.value!.price_kopecks,terms_url:plan.value!.terms_url,
  });
  if(result.checkout_url && result.status==='pending')openCheckout(result.checkout_url);
});}
onMounted(()=>action(refresh));
</script>
<template>
  <section class="panel form subscription-page">
    <p class="eyebrow">allsewpattern · Подписка</p>
    <h1>Все выкройки — в одном каталоге</h1>
    <p>Поиск по брендам, фильтры, избранное и переходы к производителям. Подписка оплачивает доступ к агрегатору, а не покупку файлов выкроек.</p>
    <p v-if="error" role="alert" class="error">{{error}}</p>
    <template v-if="plan">
      <p v-if="plan.test" class="favorite-notice">Тестовый режим ЮKassa. Реальные деньги не списываются.</p>
      <p class="price large">{{plan.price_kopecks ? rub(plan.price_kopecks)+' / 30 дней' : 'Стоимость ещё не установлена'}}</p>
      <p>Первые 7 дней бесплатно. Без привязки карты и автоматических списаний. Далее — ручное продление на 30 дней.</p>
      <p v-if="access?.has_access" role="status">{{access.state==='trial'?'Пробный доступ':'Подписка'}} до {{until(access.access_until)}}.</p>
      <p v-else-if="access?.state==='expired'">Доступ завершён. Продлите подписку, чтобы снова открыть каталог. Избранное сохранено.</p>
      <p v-if="!plan.enabled">Платная подписка пока не запущена. Пробные 7 дней не расходуются.</p>
      <p v-else-if="!tg?.initData">Откройте приложение из Telegram, чтобы активировать доступ и оплатить подписку.</p>
      <template v-else>
        <Button v-if="access?.trial_available" label="Попробовать 7 дней бесплатно" :loading="busy" @click="action(async()=>{await api('/subscription/trial','POST');})"/>
        <label v-if="plan.terms_url" class="subscription-consent"><Checkbox v-model="accepted" binary inputId="accept-subscription"/><span>Принимаю <a href="#/info/terms">условия подписки</a>. Оплата {{rub(plan.price_kopecks)}} за 30 дней, без автопродления.</span></label>
        <Button :label="`Оплатить 30 дней — ${rub(plan.price_kopecks)}`" :loading="busy" :disabled="!accepted || !plan.payments_ready || !plan.price_kopecks" @click="pay"/>
        <small>Если продлить заранее, 30 дней добавятся к оставшемуся сроку доступа.</small>
      </template>
      <small><a href="#/info/about">О сервисе и поддержка</a></small>
      <Button label="Обновить статус доступа" severity="secondary" :loading="busy" @click="action(refresh)"/>
      <template v-if="payments.length">
        <h2>История платежей</h2>
        <article v-for="p in payments" :key="p.id" class="panel form">
          <strong>{{rub(p.amount)}} · 30 дней {{p.test?'· тест':''}}</strong>
          <small>{{until(p.created)}}</small>
          <span>{{p.refunded?'Возврат — доступ по этому платежу прекращён':p.status==='succeeded'?'Оплата подтверждена':p.status==='canceled'?'Платёж отменён':'Ожидает оплаты или подтверждения'}}</span>
          <small>Номер: {{p.id}}</small>
          <Button v-if="p.status==='pending' && p.checkout_url" label="Продолжить оплату" severity="secondary" @click="openCheckout(p.checkout_url!)"/>
          <Button v-if="!p.refunded" label="Проверить платёж" severity="secondary" :loading="busy" @click="action(async()=>{await api('/subscription/payments/'+p.id+'/check','POST');})"/>
        </article>
      </template>
    </template>
  </section>
</template>
<style scoped>
.subscription-page{max-width:640px;margin:1rem auto;gap:1rem}.subscription-page h1{font-size:1.7rem}.subscription-page .subscription-consent{display:flex;flex-direction:row;align-items:flex-start;gap:.75rem}.subscription-page a{text-decoration:underline}.subscription-page small{overflow-wrap:anywhere}
</style>
