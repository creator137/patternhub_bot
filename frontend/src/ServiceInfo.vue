<script setup lang="ts">
import {onMounted,ref} from 'vue';
import Button from 'primevue/button';
import {api} from './api';
import {plan,refreshSubscription,rub} from './subscription';
defineProps<{section:string}>();
const emit=defineEmits<{back:[]}>();
const seller=ref<{full_name:string;inn:string;email:string}|null>(null),error=ref('');
async function load(){error.value='';try{seller.value=await api('/merchant');await refreshSubscription();}catch{error.value='Не удалось загрузить информацию. Попробуйте ещё раз.';}}
onMounted(load);
</script>
<template>
  <section class="service-info">
    <Button label="Назад" icon="pi pi-arrow-left" text severity="secondary" @click="emit('back')"/>
    <article class="panel form">
      <p class="eyebrow">allsewpattern</p>
      <h1>{{section==='terms'?'Условия подписки':'О сервисе'}}</h1>
      <p v-if="error" class="error" role="alert">{{error}} <Button label="Повторить" text @click="load"/></p>
      <template v-else-if="seller && plan">
        <p>Каталог выкроек с поиском по брендам, фильтрами и избранным. Файлы выкроек приобретаются отдельно у производителей.</p>
        <template v-if="section==='terms'">
          <h2>7 дней бесплатно</h2><p>Пробный период предоставляется один раз на Telegram-аккаунт и начинается по кнопке активации. Карта не требуется.</p>
          <h2>Продление на 30 дней</h2><p>Стоимость — {{plan.price_kopecks?rub(plan.price_kopecks):'пока не установлена'}}. Продление вручную, без автоматических списаний. Цена фиксируется при создании заказа; её изменение не влияет на уже оплаченный срок.</p>
          <h2>Получение доступа</h2><p>Доступ открывается после подтверждения оплаты ЮKassa для аккаунта, оформившего заказ. При досрочном продлении 30 дней добавляются к оставшемуся сроку. После окончания срока доступ к каталогу закрывается; избранное сохраняется.</p>
          <h2>Вопросы по оплате</h2><p>Если оплатили, а доступ не появился, нажмите «Проверить платёж» в истории. Для обращения к продавцу укажите номер заказа и описание проблемы. Данные банковской карты отправлять не нужно.</p>
          <p>Обращения о возврате рассматривает продавец с учётом обстоятельств покупки и применимых требований законодательства. При возврате оплаты соответствующий оплаченный период прекращается.</p>
        </template>
        <template v-else>
          <p>Первые 7 дней бесплатно, далее {{plan.price_kopecks?rub(plan.price_kopecks)+' за 30 дней':'стоимость будет опубликована позже'}}. Без автосписаний.</p>
        </template>
        <div class="seller-note">
          <p>{{seller.full_name || 'Продавец'}} · самозанятая</p>
          <p v-if="seller.inn">ИНН {{seller.inn}}</p>
          <a v-if="seller.email" :href="'mailto:'+seller.email">{{seller.email}}</a>
          <p v-else>Контакт поддержки пока не указан.</p>
        </div>
        <a v-if="section!=='terms'" href="#/info/terms">Условия подписки</a>
      </template>
    </article>
  </section>
</template>
<style scoped>
.service-info{max-width:640px;margin:1rem auto 2rem}.service-info article{margin-top:1rem;gap:1rem}.service-info h1{font-size:1.8rem}.service-info h2{font-size:1.1rem;margin-top:.75rem}.service-info p{line-height:1.65;margin:0}.seller-note{border-top:1px solid var(--p-content-border-color);padding-top:1rem;font-size:.85rem;opacity:.8;overflow-wrap:anywhere}.service-info a{text-decoration:underline;text-underline-offset:3px}
</style>
