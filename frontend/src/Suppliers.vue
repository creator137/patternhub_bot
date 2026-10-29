<script setup lang="ts">
import {computed,onMounted,ref} from 'vue';
import InputText from 'primevue/inputtext';
import {api,alphabetically,supplierSpecializations,type Supplier} from './api';
const emit=defineEmits<{browse:[supplier:Supplier]}>();
const suppliers=ref<Supplier[]>([]), search=ref(''), loading=ref(true), error=ref('');
const shown=computed(()=>{
  const needle=search.value.trim().toLocaleLowerCase('ru').replaceAll('ё','е');
  return suppliers.value.filter(s=>(s.name+' '+s.base_url).toLocaleLowerCase('ru').replaceAll('ё','е').includes(needle));
});
async function load(){
  loading.value=true;error.value='';
  try{suppliers.value=alphabetically(await api<Supplier[]>('/suppliers'),s=>s.name);}
  catch{error.value='Не удалось загрузить производителей. Попробуйте ещё раз.';}
  finally{loading.value=false;}
}
onMounted(load);
</script>
<template>
  <section class="suppliers">
    <div class="row catalog-heading"><h2>Производители выкроек</h2><span class="muted">{{shown.length}} сайтов</span></div>
    <p class="muted">Находите любимые бренды и переходите в их магазины за выкройками.</p>
    <InputText v-model="search" class="supplier-search" placeholder="Название бренда или сайта" aria-label="Поиск производителя"/>
    <p v-if="loading" role="status">Загружаем производителей…</p>
    <div v-else-if="error" role="alert"><p>{{error}}</p><button class="back" @click="load">Повторить</button></div>
    <p v-else-if="!shown.length">По этому запросу производителей нет.</p>
    <div v-else class="supplier-list">
      <article v-for="supplier in shown" :key="supplier.source" class="supplier-card">
        <span class="supplier-initial" aria-hidden="true">{{supplier.name[0]?.toLocaleUpperCase('ru')}}</span>
        <div class="supplier-info"><h3>{{supplier.name}}</h3><p>{{supplierSpecializations.find(s=>s.value===supplier.specialization)?.label || 'Выкройки'}}</p>
          <button v-if="supplier.products" class="supplier-products" @click="emit('browse',supplier)">Выкройки · {{supplier.products.toLocaleString('ru-RU')}}</button>
        </div>
        <a :href="supplier.url" target="_blank" rel="noopener noreferrer" :aria-label="'Перейти на сайт '+supplier.name" class="supplier-site">На сайт <i class="pi pi-arrow-up-right" aria-hidden="true"/></a>
      </article>
    </div>
  </section>
</template>
