<script setup lang="ts">
import {onMounted,ref} from 'vue';
import Button from 'primevue/button';
import InputText from 'primevue/inputtext';
import {api} from './api';
const merchant=ref({full_name:'',inn:'',email:''}),busy=ref(false),loaded=ref(false),error=ref(''),notice=ref('');
onMounted(async()=>{try{merchant.value=await api('/admin/merchant');loaded.value=true;}catch(e){error.value=(e as Error).message;}});
async function save(){busy.value=true;error.value='';notice.value='';try{
  merchant.value=await api('/admin/merchant','PUT',merchant.value);
  notice.value='Реквизиты опубликованы на сайте.';
}catch(e){error.value=(e as Error).message;}finally{busy.value=false;}}
</script>
<template>
  <form class="panel form" @submit.prevent="save">
    <h2>Публичные реквизиты продавца</h2>
    <p>Эти данные видны всем посетителям сайта. Указывайте только действующие реквизиты и рабочую почту.</p>
    <p v-if="error" class="error" role="alert">{{error}}</p><p v-if="notice" role="status">{{notice}}</p>
    <template v-if="loaded">
      <label>ФИО самозанятой<InputText v-model="merchant.full_name" maxlength="200"/></label>
      <label>ИНН (12 цифр)<InputText v-model="merchant.inn" inputmode="numeric" pattern="[0-9]{12}" maxlength="12"/></label>
      <label>Email поддержки<InputText v-model="merchant.email" type="email" maxlength="254" placeholder="Рабочая почта, когда будет создана"/></label>
      <Button type="submit" label="Опубликовать реквизиты" :loading="busy"/>
    </template>
    <a href="/seller" target="_blank" rel="noopener">Открыть страницу реквизитов</a>
    <a href="/subscription" target="_blank" rel="noopener">Открыть публичную страницу тарифа</a>
  </form>
</template>
