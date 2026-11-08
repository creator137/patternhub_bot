<script setup lang="ts">
import {onMounted,ref} from 'vue';
import Button from 'primevue/button';
import InputNumber from 'primevue/inputnumber';
import ToggleSwitch from 'primevue/toggleswitch';
import {api} from './api';
import {type Plan} from './subscription';
import AdminMerchant from './AdminMerchant.vue';
const emit=defineEmits<{changed:[]}>();
const value=ref<Plan|null>(null),price=ref<number|null>(null),busy=ref(false),error=ref(''),notice=ref('');
onMounted(async()=>{try{value.value=await api('/admin/subscription');price.value=value.value!.price_kopecks/100;}catch(e){error.value=(e as Error).message;}});
async function save(){busy.value=true;error.value='';notice.value='';try{
  const p=value.value!;
  value.value=await api('/admin/subscription','PUT',{enabled:p.enabled,price_kopecks:Math.round((price.value||0)*100)});
  notice.value='Настройки сохранены. Ранее созданные заказы и оплаченные сроки не изменились.';emit('changed');
}catch(e){error.value=(e as Error).message;}finally{busy.value=false;}}
</script>
<template>
  <form class="panel form" @submit.prevent="save">
    <h2>Подписка и ЮKassa</h2>
    <p v-if="error" class="error" role="alert">{{error}}</p><p v-if="notice" role="status">{{notice}}</p>
    <template v-if="value">
      <p>Первые 7 дней бесплатно, затем ручное продление на 30 дней. Автосписаний нет.</p>
      <p>{{value.test?'Тестовый':'Рабочий'}} магазин · {{value.payments_ready?'настроен':'приём платежей не настроен или выключен'}}</p>
      <label>Цена за 30 дней, ₽<InputNumber v-model="price" inputId="subscription-price" mode="currency" currency="RUB" locale="ru-RU" :min="0" :max="700000"/></label>
      <p><a href="/terms" target="_blank" rel="noopener">Условия подписки</a> уже встроены в приложение. Цена на странице обновляется автоматически.</p>
      <label class="row"><ToggleSwitch v-model="value.enabled" inputId="subscription-enabled"/>Включить платный доступ к каталогу</label>
      <p>После включения пользователям понадобится активировать пробный период или оплатить подписку. Администраторы сохраняют доступ. Секретные ключи хранятся только на сервере.</p>
      <Button label="Сохранить тариф" type="submit" :loading="busy"/>
    </template>
  </form>
  <details><summary>Реквизиты и контакт поддержки</summary><AdminMerchant/></details>
</template>
