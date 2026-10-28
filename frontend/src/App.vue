<script setup lang="ts">
import {
  computed,
  nextTick,
  onMounted,
  onUnmounted,
  reactive,
  ref,
  watch,
} from "vue";
import Button from "primevue/button";
import Drawer from "primevue/drawer";
import InputText from "primevue/inputtext";
import Select from "./CatalogSelect.vue";
import ToggleSwitch from "primevue/toggleswitch";
import Skeleton from "primevue/skeleton";
import {
  api,
  labels,
  money,
  setDevKey,
  tg,
  type Meta,
  type Page,
  type Product,
} from "./api";
import ProductImage from "./ProductImage.vue";
import ProductGallery from "./ProductGallery.vue";
import Admin from "./Admin.vue";
import { useFavorites } from './useFavorites';
const favorites = useFavorites();
const savedOnly = ref(false);
let savedReturnFilters: Record<string, string | boolean | null> | null = null;
const meta = ref<Meta | null>(null),
  items = ref<Product[]>([]),
  total = ref(0),
  loading = ref(true),
  error = ref(""),
  drawer = ref(false),
  admin = ref(false),
  loginKey = ref(""),
  loginError = ref("");
const route = ref(location.hash),
  detail = ref<Product | null>(null),
  detailError = ref(""),
  detailLoading = ref(false);
const filters = reactive<Record<string, string | boolean | null>>({
  search: "",
  category: null,
  source: null,
  audience: null,
  is_new: null,
  is_sale: null,
  is_free: null,
  is_beginner: null,
  is_knit: null,
  sort: "name",
});
try {
  const stored = JSON.parse(sessionStorage.getItem('allsewpattern.filters') || '{}');
  for (const key of Object.keys(filters))
    if (stored && key in stored && (stored[key] === null || ['string', 'boolean'].includes(typeof stored[key]))) filters[key] = stored[key];
} catch { /* browsing remains available without storage */ }
let listRequest: AbortController | null = null;
const sortOptions = [
  { label: "Сначала новинки", value: "new_first" },
  { label: "По названию", value: "name" },
  { label: "Сначала дешевле", value: "price_asc" },
  { label: "Сначала дороже", value: "price_desc" },
];
const audienceOptions = ["women", "men", "kids", "unisex"].map((value) => ({
  label: labels[value],
  value,
}));
const enabled = computed(
  () => meta.value?.ui.filters.filter((x) => x.enabled).map((x) => x.key) || [],
);
const quick = computed(() =>
  enabled.value.filter((x) => ["is_new", "is_sale", "is_free"].includes(x)),
);
const count = computed(
  () => Object.entries(filters).filter(([k, v]) => k !== "sort" && v).length,
);
let requestId = 0,
  detailId = 0,
  timer: ReturnType<typeof setTimeout>,
  scroll = 0;
function query(offset = 0) {
  const p = new URLSearchParams({ offset: String(offset) });
  if (savedOnly.value) p.set('ids', favorites.ids.value.join(','));
  for (const [key, value] of Object.entries(filters))
    if (enabled.value.includes(key) && value !== null && value !== "")
      p.set(key, String(value));
  return p;
}
async function load(more = false) {
  const id = ++requestId;
  listRequest?.abort();
  listRequest = new AbortController();
  loading.value = true;
  error.value = "";
  if (savedOnly.value && !favorites.ids.value.length) {
    items.value = []; total.value = 0; loading.value = false; return;
  }
  try {
    const result = await api<Page>(
      "/products?" + query(more ? items.value.length : 0),
      'GET', undefined, listRequest.signal,
    );
    if (id !== requestId) return;
    items.value = more ? [...items.value, ...result.items] : result.items;
    total.value = result.total;
  } catch (e) {
    if (id === requestId) error.value = (e as Error).message;
  } finally {
    if (id === requestId) loading.value = false;
  }
}
async function refreshMeta() {
  meta.value = await api<Meta>("/meta");
  for (const key of Object.keys(filters))
    if (!enabled.value.includes(key))
      filters[key] = key === "sort" ? "name" : null;
}
function reset() {
  for (const key in filters) filters[key] = key === "sort" ? "name" : null;
}
function toggle(key: string) {
  filters[key] = filters[key] ? null : true;
}
function toggleSavedView() {
  if (!savedOnly.value) {
    savedReturnFilters = { ...filters };
    reset(); savedOnly.value = true;
  } else {
    savedOnly.value = false;
    if (savedReturnFilters) Object.assign(filters, savedReturnFilters);
  }
  location.hash = '';
  window.scrollTo(0, 0);
  load();
}
watch(favorites.ids, () => { if (savedOnly.value) load(); });
function selectSection(audience: string | null) {
  // Header tabs are navigation; the Drawer still supports combined filters.
  for (const key in filters) if (key !== 'sort') filters[key] = null;
  filters.audience = audience;
}
const activeFilters = computed(() => Object.entries(filters)
  .filter(([key, value]) => key !== 'sort' && key !== 'audience' && !!value)
  .map(([key, value]) => ({key, title: key.startsWith('is_') ? labels[key] :
    `${labels[key]}: ${key === 'source' ? meta.value?.brands.find(b => b.source === value)?.name || value : value}`})));
function openAdmin() {
  location.hash = "/admin";
}
function open(p: Product) {
  scroll = window.scrollY;
  location.hash = "/product/" + p.id;
}
function back() {
  location.hash = "";
  nextTick(() => window.scrollTo(0, scroll));
}
async function routeChanged() {
  route.value = location.hash;
  const id = ++detailId;
  if (route.value.startsWith("#/product/")) {
    detail.value = null;
    detailError.value = "";
    detailLoading.value = true;
    tg?.BackButton.show();
    window.scrollTo(0, 0);
    try {
      const p = await api<Product>(
        "/products/" + encodeURIComponent(route.value.slice(10)),
      );
      if (id === detailId) detail.value = p;
    } catch (e) {
      if (id === detailId) detailError.value = (e as Error).message;
    } finally {
      if (id === detailId) detailLoading.value = false;
    }
  } else {
    tg?.BackButton.hide();
    if (!route.value) nextTick(() => window.scrollTo(0, scroll));
  }
}
function theme() {
  document.documentElement.classList.toggle(
    "dark",
    tg?.initData
      ? tg.colorScheme === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches,
  );
}
async function login() {
  setDevKey(loginKey.value);
  loginKey.value = "";
  loginError.value = "";
  try {
    await api("/admin/session");
    admin.value = true;
  } catch (e) {
    setDevKey("");
    loginError.value = (e as Error).message;
  }
}
async function changed() {
  try {
    await refreshMeta();
    await load();
  } catch (e) {
    error.value = (e as Error).message;
  }
}
watch(filters, () => {
  try { sessionStorage.setItem('allsewpattern.filters', JSON.stringify(filters)); } catch { /* optional storage */ }
  clearTimeout(timer);
  ++requestId;
  timer = setTimeout(() => load(), 250);
});
const scheme = window.matchMedia("(prefers-color-scheme: dark)");
onMounted(async () => {
  theme();
  scheme.addEventListener("change", theme);
  tg?.ready();
  tg?.expand();
  tg?.onEvent("themeChanged", theme);
  tg?.BackButton.onClick(back);
  window.addEventListener("hashchange", routeChanged);
  try {
    await refreshMeta();
    await load();
    await favorites.initialize();
    if (tg?.initData) {
      try {
        await api("/admin/session");
        admin.value = true;
      } catch {
        /* public browsing remains available */
      }
    }
    await routeChanged();
  } catch (e) {
    error.value = (e as Error).message;
    loading.value = false;
  }
});
onUnmounted(() => {
  listRequest?.abort();
  clearTimeout(timer);
  window.removeEventListener("hashchange", routeChanged);
  scheme.removeEventListener("change", theme);
  tg?.offEvent("themeChanged", theme);
  tg?.BackButton.offClick(back);
});
</script>
<template>
  <header class="header">
    <a href="#" class="logo"
      ><img class="logo-image" src="/brand/avatar.jpg" alt="" />
      <span>allsewpattern</span></a
    >
    <div class="header-right">
      <button class="icon-btn saved-nav" :class="{ active: savedOnly }" :aria-label="'Избранное (' + favorites.ids.value.length + ')'" title="Избранное" @click="toggleSavedView">
        <i :class="savedOnly ? 'pi pi-heart-fill' : 'pi pi-heart'" /><span v-if="favorites.ids.value.length" class="saved-count">{{ favorites.ids.value.length }}</span>
      </button><button
        v-if="admin || meta?.local_login"
        class="icon-btn"
        aria-label="Управление"
        @click="openAdmin"
      >
        <i class="pi pi-sliders-h"></i>
      </button>
    </div>
  </header>
  <main>
    <div v-if="favorites.notice.value" class="favorite-notice" role="status">{{ favorites.notice.value }}<button class="icon-btn" aria-label="Закрыть уведомление" @click="favorites.notice.value = ''"><i class="pi pi-times" /></button></div>
    <template v-if="route === '#/admin'"
      ><button class="back" @click="back">← В каталог</button
      ><Admin v-if="admin && meta" :meta="meta" @changed="changed" />
      <section v-else class="panel form">
        <h1>Доступ администратора</h1>
        <p>Войдите через Telegram с разрешённым user_id.</p>
        <form v-if="meta?.local_login" class="form" @submit.prevent="login">
          <label
            >Локальный ключ<InputText
              v-model="loginKey"
              type="password"
              autocomplete="off" /></label
          ><Button label="Войти локально" type="submit" />
        </form>
        <p v-if="loginError" class="error" role="alert">{{ loginError }}</p>
      </section></template
    >
    <template v-else-if="route.startsWith('#/product/')"
      ><button class="back" @click="back">← К выкройкам</button
      ><Skeleton v-if="detailLoading" height="30rem" />
      <div v-else-if="detailError" class="empty" role="alert">
        <h2>Не удалось открыть выкройку</h2>
        <p>{{ detailError }}</p>
        <Button label="Повторить" @click="routeChanged" />
      </div>
      <article v-else-if="detail" class="detail">
        <ProductGallery :product="detail" />
        <div class="detail-info">
          <p class="eyebrow">{{ detail.brand || detail.source }}</p>
          <h1>{{ detail.name }}</h1>
          <button class="detail-save" :aria-pressed="favorites.ids.value.includes(detail.id)" :disabled="favorites.pending.value.has(detail.id)" @click="favorites.toggle(detail.id)">
            <i :class="favorites.ids.value.includes(detail.id) ? 'pi pi-heart-fill' : 'pi pi-heart'" />{{ favorites.ids.value.includes(detail.id) ? 'В избранном' : 'В избранное' }}
          </button>
          <p class="price large">
            {{ money(detail) }}
            <del v-if="detail.is_sale && detail.old_price">{{
              detail.old_price
            }}</del>
          </p>
          <div class="chips">
            <span v-if="detail.is_new">Новинка у бренда</span
            ><span v-if="detail.is_sale">Скидка</span
            ><span v-if="detail.is_beginner">Для начинающих</span
            ><span v-if="detail.is_knit">Трикотаж</span>
          </div>
          <dl>
            <template
              v-for="entry in [
                ['Категория', detail.category],
                ['Для кого', detail.audience ? labels[detail.audience] : null],
                ['Размеры', detail.sizes?.join(', ')],
                ['Рост', detail.heights?.join(', ')],
                ['Сложность', detail.difficulty],
              ]"
              :key="entry[0] || ''"
              ><template v-if="entry[1]"
                ><dt>{{ entry[0] }}</dt>
                <dd>{{ entry[1] }}</dd></template
              ></template
            >
          </dl>
          <p class="description">
            {{
              detail.description ||
              "Подробности, состав комплекта и рекомендации по материалам — на сайте производителя."
            }}
          </p>
          <a
            v-if="detail.product_url"
            class="store-link"
            :href="detail.product_url"
            target="_blank"
            rel="noopener noreferrer"
            >Перейти в магазин <i class="pi pi-arrow-up-right"></i
          ></a>
          <p class="muted small">
            Цена и наличие уточняются у продавца. allsewpattern помогает найти
            выкройку.
          </p>
        </div>
      </article></template
    >
    <template v-else>
      <section class="catalog">
        <div class="row catalog-heading">
          <div>
            <h2>{{ savedOnly ? 'Избранное' : 'Каталог выкроек' }}</h2>
          </div>
          <span class="muted" aria-live="polite"
            >{{ total.toLocaleString("ru-RU") }} найдено</span
          >
        </div>
        <nav
          v-if="enabled.includes('audience')"
          class="audiences"
          aria-label="Для кого"
        >
          <button
            :class="{ active: !filters.audience }"
            @click="selectSection(null)"
          >
            Все выкройки</button
          ><button
            v-for="entry in meta?.ui.menu.filter((x) => x.enabled)"
            :key="entry.key"
            :class="{ active: filters.audience === entry.key }"
            :disabled="meta?.coverage.counts[entry.key] === 0"
            :title="meta?.coverage.counts[entry.key] === 0 ? 'Нет товаров с подтверждённой аудиторией' : 'Количество во всём каталоге'"
            @click="selectSection(entry.key)"
          >
            {{ labels[entry.key] }} <small>{{ meta?.coverage.counts[entry.key] }}</small>
          </button>
        </nav>
        <div class="toolbar">
          <div v-if="enabled.includes('search')" class="search">
            <i class="pi pi-search"></i
            ><InputText
              v-model="filters.search as string"
              placeholder="Найти платье, жакет, свою идею…"
              aria-label="Поиск выкроек"
            />
          </div>
          <Button
            label="Фильтры"
            icon="pi pi-sliders-h"
            :badge="count ? String(count) : undefined"
            outlined
            @click="drawer = true"
            aria-controls="filters"
            :aria-expanded="drawer"
          /><Select
            v-if="enabled.includes('sort')"
            v-model="filters.sort"
            class="desktop"
            :options="sortOptions"
            optionLabel="label"
            optionValue="value"
            aria-label="Сортировка"
          />
        </div>
        <nav
          v-if="enabled.includes('category')"
          class="chips categories"
          aria-label="Категории"
        >
          <button
            :class="{ active: !filters.category }"
            @click="filters.category = null"
          >
            Все категории</button
          ><button
            v-for="c in meta?.categories"
            :key="c.name"
            :class="{ active: filters.category === c.name }"
            @click="filters.category = c.name"
          >
            {{ c.name }} <small>{{ c.count }}</small>
          </button>
        </nav>
        <div class="chips quick">
          <button
            v-for="key in quick"
            :key="key"
            :class="{ active: filters[key] }"
            :disabled="meta?.coverage.counts[key] === 0"
            :title="meta?.coverage.counts[key] === 0 ? 'Нет товаров с подтверждённым признаком' : 'Количество во всём каталоге'"
            @click="toggle(key)"
          >
            <i
              aria-hidden="true"
              :class="
                'pi ' +
                (key === 'is_new'
                  ? 'pi-sparkles'
                  : key === 'is_sale'
                    ? 'pi-tag'
                    : 'pi-gift')
              "
            ></i
            >{{ labels[key] }} <small>{{ meta?.coverage.counts[key] }}</small></button
          ><button v-if="count" class="reset" @click="reset">
            Сбросить · {{ count }}
          </button>
        </div>
        <div v-if="activeFilters.length" class="chips active-filters" aria-label="Выбранные фильтры">
          <button v-for="entry in activeFilters" :key="entry.key" :aria-label="'Убрать фильтр: ' + entry.title" @click="filters[entry.key] = null">
            {{ entry.title }} <span aria-hidden="true">×</span>
          </button>
        </div>
        <p v-if="meta?.coverage.unknown_audience" class="muted small" role="note">
          У {{ meta.coverage.unknown_audience }} выкроек аудитория пока не определена:
          они доступны в разделе «Все выкройки».
        </p>
        <p v-if="filters.is_new" class="muted small" role="note">
          Только подтверждённые новинки. Не все источники передают этот признак.
          <button v-if="enabled.includes('sort')" class="reset" @click="filters.is_new = null; filters.sort = 'new_first'">
            Весь каталог, сначала новинки
          </button>
        </p>
        <div v-if="error" class="empty" role="alert">
          <h2>Каталог временно недоступен</h2>
          <p>{{ error }}</p>
          <Button label="Попробовать снова" @click="changed" />
        </div>
        <div v-else-if="loading && !items.length" class="product-grid">
          <div v-for="n in 8" :key="n">
            <Skeleton height="250px" /><Skeleton
              width="70%"
              class="skeleton-line"
            /><Skeleton width="40%" />
          </div>
        </div>
        <div v-else-if="!items.length" class="empty">
          <i class="pi pi-search"></i>
          <h2>{{ savedOnly && !favorites.ids.value.length ? 'Здесь будут любимые выкройки' : 'Пока ничего не нашлось' }}</h2>
          <p>
            {{ savedOnly && !favorites.ids.value.length ? 'Сохраняйте понравившиеся модели сердечком.' : 'Попробуйте другой бренд, название или уберите часть фильтров.' }}
          </p>
          <Button v-if="savedOnly && !favorites.ids.value.length" label="В каталог" outlined @click="toggleSavedView" />
          <Button v-else label="Сбросить фильтры" outlined @click="reset" />
        </div>
        <div v-else class="product-grid" :aria-busy="loading">
          <article
            v-for="(p, index) in items"
            :key="p.id"
            class="product-card"
          >
            <a class="product-open" :href="'#/product/' + p.id" @click.prevent="open(p)">
            <ProductImage :src="p.thumbnail_url || p.image_url" :fallback-src="p.image_url" :alt="p.name" :eager="index < 4"
              ><div class="badges">
                <span v-if="p.is_new">NEW</span
                ><span v-if="p.is_sale" class="sale">СКИДКА</span
                ><span v-if="p.is_free">БЕСПЛАТНО</span>
              </div>
              <span class="card-arrow"
                ><i class="pi pi-arrow-up-right"></i></span
              ><span v-if="p.image_count && p.image_count > 1" class="photo-count"><i class="pi pi-images" /> {{ p.image_count }}</span
            ></ProductImage>
            <div class="card-info">
              <p class="brand">{{ p.brand || p.source }}</p>
              <h3>{{ p.name }}</h3>
              <p class="price">
                {{ money(p) }}
                <del v-if="p.is_sale && p.old_price">{{
                  Number(p.old_price).toLocaleString("ru-RU")
                }}</del>
              </p>
            </div>
            </a>
            <button class="save-product" :aria-label="(favorites.ids.value.includes(p.id) ? 'Убрать из избранного: ' : 'Сохранить: ') + p.name" :aria-pressed="favorites.ids.value.includes(p.id)" :disabled="favorites.pending.value.has(p.id)" :title="favorites.ids.value.includes(p.id) ? 'Убрать из избранного' : 'В избранное'" @click="favorites.toggle(p.id)">
              <i :class="favorites.ids.value.includes(p.id) ? 'pi pi-heart-fill' : 'pi pi-heart'" />
            </button>
          </article>
        </div>
        <div v-if="items.length < total && !error" class="load-more">
          <Button
            label="Показать ещё"
            outlined
            :loading="loading"
            @click="load(true)"
          />
          <p class="muted small">{{ items.length }} из {{ total }} выкроек</p>
        </div>
      </section></template
    >
  </main>
  <footer>
    <a href="#" class="logo">allsewpattern</a>
    <p>Место, где идеи обретают форму.</p>
    <span>Сервис по подбору выкроек · цены уточняйте у брендов</span>
  </footer>
  <Drawer
    id="filters"
    v-model:visible="drawer"
    header="Найти свою выкройку"
    position="bottom"
    class="filter-drawer"
    ><div class="filter-fields">
      <template v-for="key in enabled" :key="key"
        ><label v-if="['category', 'source', 'audience', 'sort'].includes(key)"
          >{{ labels[key]
          }}<Select
            v-if="key === 'category'"
            v-model="filters.category"
            :options="meta?.categories"
            optionLabel="name"
            optionValue="name"
            showClear
            placeholder="Все категории" /><Select
            v-if="key === 'source'"
            v-model="filters.source"
            :options="meta?.brands"
            optionLabel="name"
            optionValue="source"
            showClear
            placeholder="Все бренды" /><Select
            v-if="key === 'audience'"
            v-model="filters.audience"
            :options="audienceOptions"
            optionLabel="label"
            optionValue="value"
            showClear
            placeholder="Все" /><Select
            v-if="key === 'sort'"
            v-model="filters.sort"
            :options="sortOptions"
            optionLabel="label"
            optionValue="value" /></label
        ><label v-else-if="key.startsWith('is_')" class="toggle-row"
          ><span>{{ labels[key] }}</span
          ><ToggleSwitch
            :modelValue="!!filters[key]"
            @update:modelValue="
              (v) => (filters[key] = v ? true : null)
            " /></label
      ></template>
    </div>
    <template #footer
      ><div class="row">
        <Button label="Сбросить" text @click="reset" /><Button
          :label="'Показать · ' + total"
          :loading="loading"
          @click="drawer = false"
        /></div></template
  ></Drawer>
</template>
