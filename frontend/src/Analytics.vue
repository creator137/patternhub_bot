<script setup lang="ts">
import {onMounted,ref} from 'vue';
import Button from 'primevue/button';
import {api} from './api';
import type {AnalyticsSummary} from './analytics';
const days=ref(30), data=ref<AnalyticsSummary|null>(null), loading=ref(false), error=ref('');
async function load() {
  loading.value=true; error.value='';
  try {data.value=await api<AnalyticsSummary>('/admin/analytics?days='+days.value);}
  catch(e) {error.value=(e as Error).message;}
  finally {loading.value=false;}
}
function date(value:string) {return new Date(value+'T00:00:00Z').toLocaleDateString('ru-RU',{timeZone:'UTC'});}
onMounted(load);
</script>
<template>
  <section class="analytics">
    <div class="row">
      <h2>Статистика приложения</h2>
      <label>Период <select v-model="days" :disabled="loading" @change="load" aria-label="Период статистики">
        <option :value="1">Сегодня</option><option :value="7">7 дней</option>
        <option :value="30">30 дней</option><option :value="90">90 дней</option>
      </select></label>
      <Button label="Обновить" :loading="loading" :disabled="loading" @click="load" />
    </div>
    <p v-if="error" role="alert" class="error">{{error}}</p>
    <p v-if="loading" role="status">Загружаем статистику…</p>
    <template v-else-if="data && !error">
      <div class="admin-grid">
        <article class="panel"><h3>{{data.users.toLocaleString('ru-RU')}}</h3><p>Уникальные пользователи</p></article>
        <article class="panel"><h3>{{data.opens.toLocaleString('ru-RU')}}</h3><p>Открытия приложения</p></article>
        <article class="panel"><h3>{{data.clicks.toLocaleString('ru-RU')}}</h3><p>Переходы на сайты</p></article>
        <article class="panel"><h3>{{data.outbound_users.toLocaleString('ru-RU')}}</h3><p>Пользователи, перешедшие на сайты</p></article>
      </div>
      <p class="muted">{{data.since ? 'Данные собираются с '+date(data.since.slice(0,10))+'.' : 'Данных пока нет. Статистика появится после первых посещений из Telegram.'}}
        Дни считаются по UTC. Учитываются пользователи с подтверждённой сессией Telegram.
        Повторное открытие или перезагрузка приложения считается новым открытием.</p>
      <h3>Переходы к производителям</h3>
      <p v-if="!data.sources.length" class="muted">За этот период переходов пока нет.</p>
      <div v-else class="analytics-table"><table>
        <thead><tr><th>Производитель</th><th>Переходы</th><th>Пользователи</th></tr></thead>
        <tbody><tr v-for="s in data.sources" :key="s.source"><td>{{s.name}}</td><td>{{s.clicks}}</td><td>{{s.users}}</td></tr></tbody>
      </table></div>
      <h3>По дням</h3>
      <div class="analytics-table"><table>
        <thead><tr><th>Дата</th><th>Пользователи</th><th>Открытия</th><th>Переходы</th></tr></thead>
        <tbody><tr v-for="day in [...data.daily].reverse()" :key="day.day"><td>{{date(day.day)}}</td><td>{{day.users}}</td><td>{{day.opens}}</td><td>{{day.clicks}}</td></tr></tbody>
      </table></div>
      <p class="muted">Переход — нажатие на ссылку магазина в карточке или в разделе «Производители».
        Покупки и завершение загрузки сайта магазина не отслеживаются. Пользователи за период считаются без повторов;
        суммы по дням и производителям могут включать одного человека несколько раз.</p>
    </template>
  </section>
</template>
<style scoped>
.analytics .row {flex-wrap:wrap;gap:12px}
.analytics select {font:inherit;padding:8px;border:1px solid var(--line,#ddd);border-radius:8px;background:var(--paper,#fff);color:inherit}
.analytics-table {overflow-x:auto;max-width:100%}
table {width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td {padding:12px 8px;text-align:left;border-bottom:1px solid var(--line,#ddd)}
th {font-size:13px} td:first-child {min-width:100px}
</style>
