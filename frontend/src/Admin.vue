<script setup lang="ts">
import { nextTick, onMounted, ref } from "vue";
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import Select from "./CatalogSelect.vue";
import ToggleSwitch from "primevue/toggleswitch";
import {
  api,
  labels,
  money,
  type Meta,
  type Source,
  type Page,
  type Product,
  type UISettings,
  type UIItem,
  alphabetically,
  supplierSpecializations,
} from "./api";
import ProductImage from "./ProductImage.vue";
const props = defineProps<{ meta: Meta }>();
const media = ref<{ total: number; cached: number; queue: Record<string, number>; gallery_errors: number } | null>(null);
const emit = defineEmits<{ changed: [] }>();
const tab = ref("sources"),
  sources = ref<Source[]>([]),
  error = ref(""),
  notice = ref(""),
  busy = ref(false);
const ui = ref<UISettings>(JSON.parse(JSON.stringify(props.meta.ui)));
const name = ref(""),
  url = ref(""),
  specialization = ref('general'),
  search = ref(""),
  products = ref<Product[]>([]),
  total = ref(0),
  selected = ref<Product | null>(null),
  category = ref<string | null>(null);
async function action(fn: () => Promise<void>) {
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    await fn();
    notice.value = "Сохранено";
    emit("changed");
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}
async function loadSources() {
  sources.value = alphabetically(await api<Source[]>("/admin/sources"),source=>source.display_name);
  try { media.value = await api('/admin/media'); } catch { /* Source management remains available. */ }
}
async function loadProducts(more = false) {
  const p = await api<Page>(
    `/admin/products?search=${encodeURIComponent(search.value)}&offset=${more ? products.value.length : 0}`,
  );
  products.value = more ? [...products.value, ...p.items] : p.items;
  total.value = p.total;
}
async function changeTab(value: string) {
  tab.value = value;
  error.value = "";
  try {
    if (value === "products") await loadProducts();
  } catch (e) {
    error.value = (e as Error).message;
  }
}
function move(list: UIItem[], entry:UIItem) {
  const index=list.indexOf(entry);
  const previous=index-1;
  if(previous>=0)[list[previous],list[index]]=[list[index],list[previous]];
}
function edit(p: Product) {
  selected.value = p;
  category.value = p.category === p.imported_category ? null : p.category;
  nextTick(() => document.querySelector('.admin .form:last-child')?.scrollIntoView({block:'start',behavior:'smooth'}));
}
onMounted(async () => {
  try {
    await loadSources();
  } catch (e) {
    error.value = (e as Error).message;
  }
});
</script>
<template>
  <section class="admin">
    <p class="eyebrow">РАБОЧЕЕ ПРОСТРАНСТВО</p>
    <h1>Управление</h1>
    <p class="muted">Настройки витрины и общий каталог всех источников.</p>
    <div v-if="media" class="media-health">
      <span><strong>{{ media.cached }} / {{ media.total }}</strong> Обложки в кэше</span>
      <span><strong>{{ media.queue.pending || 0 }}</strong> Ожидают загрузки</span>
      <span><strong>{{ media.queue.retry || 0 }}</strong> Повторные попытки</span>
      <button class="icon-btn" aria-label="Обновить состояние фото" title="Обновить состояние фото" @click="loadSources"><i class="pi pi-refresh" /></button>
    </div>
    <nav class="chips">
      <button
        v-for="item in [
          ['sources', 'Источники'],
          ['filters', 'Фильтры каталога'],
          ['products', 'Товары'],
        ]"
        :key="item[0]"
        :class="{ active: tab === item[0] }"
        @click="changeTab(item[0])"
      >
        {{ item[1] }}
      </button>
    </nav>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <template v-if="tab === 'sources'"
      ><div class="admin-grid">
        <article v-for="s in sources" :key="s.name" class="panel">
          <div class="row">
            <h3>{{ s.display_name }}</h3>
            <ToggleSwitch
              :modelValue="!!s.enabled"
              :disabled="busy"
              :aria-label="'Включить ' + s.display_name"
              @update:modelValue="
                (value) =>
                  action(async () => {
                    await api('/admin/sources/' + s.name, 'PATCH', {
                      enabled: value,
                    });
                    await loadSources();
                  })
              "
            />
          </div>
          <a :href="s.base_url" target="_blank" rel="noopener noreferrer">{{
            s.base_url
          }}</a>
          <p>{{ s.products }} товаров</p>
          <small :class="{ muted: s.parser_status === 'pending' }">{{
            s.products > 0
              ? "Выкройки доступны в каталоге"
              : "Переход на сайт поставщика"
          }}</small>
        </article>
      </div>
      <form
        class="panel form"
        @submit.prevent="
          action(async () => {
            await api('/admin/sources', 'POST', {
              display_name: name,
              base_url: url,
              specialization,
            });
            name = '';
            url = '';
            specialization = 'general';
            await loadSources();
          })
        "
      >
        <h2>Добавить источник</h2>
        <label
          >Название<InputText v-model="name" required maxlength="100" /></label
        ><label
          >Адрес сайта<InputText
            v-model="url"
            type="url"
            placeholder="https://"
            required
        /></label>
        <label>Направление<Select v-model="specialization" :options="supplierSpecializations" optionLabel="label" optionValue="value" aria-label="Направление поставщика"/></label>
        <p class="muted">
          После включения сайт появится в разделе «Поставщики». Отдельные выкройки
          добавляются после подключения каталога.
        </p>
        <Button type="submit" label="Добавить сайт" :disabled="busy" /></form
    ></template>
    <template v-if="tab === 'filters'"
      ><div class="admin-grid">
        <section
          v-for="group in ['filters', 'menu'] as const"
          :key="group"
          class="panel"
        >
          <h2>{{ group === 'filters' ? 'Фильтры' : 'Разделы по аудитории' }}</h2>
          <div
            v-for="(entry, index) in ui[group]"
            :key="entry.key"
            class="setting-row"
          >
            <ToggleSwitch
              v-model="entry.enabled"
              :aria-label="labels[entry.key]"
            /><span>{{ labels[entry.key] }}</span
            ><Button
              icon="pi pi-arrow-up"
              :aria-label="'Поднять ' + labels[entry.key]"
              :disabled="index === 0"
              text
              @click="move(ui[group], entry)"
            />
          </div>
        </section>
      </div>
      <Button
        label="Сохранить настройки"
        :disabled="busy"
        @click="
          action(async () => {
            await api('/admin/settings', 'PUT', ui);
          })
        "
    /></template>
    <template v-if="tab === 'products'"
      ><form class="row" @submit.prevent="action(() => loadProducts())">
        <InputText
          v-model="search"
          placeholder="Поиск во всех товарах"
          aria-label="Поиск во всех товарах"
        /><Button label="Найти" type="submit" :disabled="busy" />
      </form>
      <p class="muted">
        {{ total }} записей · включая скрытые и отключённые источники
      </p>
      <div class="admin-grid">
        <button
          v-for="p in products"
          :key="p.id"
          class="panel admin-product"
          @click="edit(p)"
        >
          <ProductImage :src="p.image_url" :alt="p.name" />
          <div>
            <small>{{ p.brand || p.source }}</small>
            <h3>{{ p.name }}</h3>
            <p>{{ money(p) }}</p>
            <small>{{
              p.hidden
                ? "Скрыт вручную"
                : !p.is_available
                  ? "Недоступен"
                  : !p.source_enabled
                    ? "Источник выключен"
                    : "В каталоге"
            }}</small>
          </div>
        </button>
      </div>
      <Button
        v-if="products.length < total"
        label="Показать ещё"
        :disabled="busy"
        @click="action(() => loadProducts(true))" />
      <section v-if="selected" class="panel form">
        <h2>{{ selected.name }}</h2>
        <p>{{ selected.description || "Описание отсутствует" }}</p>
        <p>
          Категория парсера: {{ selected.imported_category || "не задана" }}
        </p>
        <label
          >Внутренняя категория<Select
            v-model="category"
            :options="meta.category_options"
            showClear
            placeholder="Использовать категорию парсера" /></label
        ><label class="row"
          ><ToggleSwitch v-model="selected.hidden" />Скрыть из витрины</label
        ><a
          v-if="selected.product_url"
          :href="selected.product_url"
          target="_blank"
          rel="noopener noreferrer"
          >Оригинал в магазине ↗</a
        ><Button
          label="Сохранить товар"
          :disabled="busy"
          @click="
            action(async () => {
              await api('/admin/products/' + selected!.id, 'PATCH', {
                hidden: !!selected!.hidden,
                category,
              });
              await loadProducts();
              selected = null;
            })
          "
        /></section
    ></template>
  </section>
</template>
