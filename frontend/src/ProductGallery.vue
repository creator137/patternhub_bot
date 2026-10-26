<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted } from 'vue';
import Dialog from 'primevue/dialog';
import ProductImage from './ProductImage.vue';
import type { Product } from './api';
const props = defineProps<{ product: Product }>();
const index = ref(0), expanded = ref(false), zoomed = ref(false);
const thumbs = ref<HTMLElement | null>(null), visibleThumbs = ref(new Set([0, 1, 2]));
let observer: IntersectionObserver | null = null;
const photos = computed(() => props.product.photo_urls?.length ? props.product.photo_urls :
  props.product.image_url ? [props.product.image_url] : []);
let touch: { x: number; y: number } | null = null;
watch(() => props.product.id, () => { index.value = 0; expanded.value = false; });
watch(index, value => {
  for (let i = Math.max(0, value - 2); i <= value + 2; i++) visibleThumbs.value.add(i);
});
onMounted(() => {
  if (!thumbs.value) return;
  observer = new IntersectionObserver(entries => {
    for (const entry of entries) if (entry.isIntersecting) visibleThumbs.value.add(Number((entry.target as HTMLElement).dataset.photoIndex));
  }, { root: thumbs.value, rootMargin: '0px 100px' });
  for (const element of Array.from(thumbs.value.children)) observer.observe(element);
});
onUnmounted(() => observer?.disconnect());
function move(step: number) {
  if (photos.value.length) index.value = (index.value + step + photos.value.length) % photos.value.length;
  zoomed.value = false;
}
function start(event: TouchEvent) { touch = { x: event.changedTouches[0].clientX, y: event.changedTouches[0].clientY }; }
function end(event: TouchEvent) {
  if (!touch || zoomed.value) return;
  const dx = event.changedTouches[0].clientX - touch.x, dy = event.changedTouches[0].clientY - touch.y;
  if (Math.abs(dx) > 45 && Math.abs(dx) > Math.abs(dy) * 1.5) move(dx < 0 ? 1 : -1);
  touch = null;
}
</script>
<template>
  <section class="gallery" aria-label="Фотографии выкройки" @keydown.left="move(-1)" @keydown.right="move(1)">
    <div class="gallery-stage" @touchstart.passive="start" @touchend.passive="end">
      <button class="gallery-main" :aria-label="'Увеличить фото: ' + product.name" @click="expanded = true; zoomed = false">
        <ProductImage :src="photos[index] || null" :fallback-src="product.image_urls?.[index] || product.image_url" :alt="product.name + ', фото ' + (index + 1)" eager />
        <span class="gallery-expand"><i class="pi pi-expand" /></span>
      </button>
      <template v-if="photos.length > 1">
        <button class="gallery-arrow previous" aria-label="Предыдущее фото" title="Предыдущее фото" @click="move(-1)"><i class="pi pi-chevron-left" /></button>
        <button class="gallery-arrow next" aria-label="Следующее фото" title="Следующее фото" @click="move(1)"><i class="pi pi-chevron-right" /></button>
        <span class="gallery-counter" aria-live="polite">{{ index + 1 }} / {{ photos.length }}</span>
      </template>
    </div>
    <div v-if="photos.length > 1" ref="thumbs" class="gallery-thumbs" aria-label="Выбор фото">
      <button v-for="(_, i) in photos" :key="i" :data-photo-index="i" :aria-label="'Фото ' + (i + 1)" :aria-pressed="index === i" :class="{ selected: index === i }" @click="index = i">
        <ProductImage v-if="visibleThumbs.has(i)" :src="product.photo_thumbnails?.[i] || photos[i]" :fallback-src="product.image_urls?.[i]" alt="" />
      </button>
    </div>
    <Dialog v-model:visible="expanded" modal dismissable-mask :header="product.name" class="photo-dialog" :style="{ width: 'min(96vw, 1100px)' }" @hide="zoomed = false" @keydown.left="move(-1)" @keydown.right="move(1)">
      <div class="lightbox" :class="{ zoomed }" @touchstart.passive="start" @touchend.passive="end">
        <button class="zoom-control" :aria-label="zoomed ? 'Уменьшить фото' : 'Увеличить фото'" @click="zoomed = !zoomed"><i :class="zoomed ? 'pi pi-search-minus' : 'pi pi-search-plus'" /></button>
        <ProductImage :src="photos[index] || null" :fallback-src="product.image_urls?.[index] || product.image_url" :alt="product.name" eager />
      </div>
      <template #footer>
        <div class="lightbox-controls">
          <button class="icon-btn" aria-label="Предыдущее фото" :disabled="photos.length < 2" @click="move(-1)"><i class="pi pi-chevron-left" /></button>
          <span>{{ photos.length ? index + 1 : 0 }} / {{ photos.length }}</span>
          <button class="icon-btn" aria-label="Следующее фото" :disabled="photos.length < 2" @click="move(1)"><i class="pi pi-chevron-right" /></button>
        </div>
      </template>
    </Dialog>
  </section>
</template>
<style scoped>
.gallery { min-width: 0; }
.gallery-stage { position: relative; touch-action: pan-y pinch-zoom; }
.gallery-main { display: block; width: 100%; padding: 0; border: 0; background: transparent; cursor: zoom-in; }
.gallery-main :deep(.photo img) { object-fit: contain; }
.gallery-expand, .gallery-arrow, .gallery-counter { position: absolute; background: var(--paper); color: var(--ink); }
.gallery-expand { bottom: 14px; right: 14px; padding: 10px; border-radius: 4px; }
.gallery-arrow { top: 45%; width: 44px; height: 44px; border: 1px solid var(--line); border-radius: 50%; cursor: pointer; }
.previous { left: 10px; } .next { right: 10px; }
.gallery-counter { bottom: 14px; left: 14px; padding: 8px 12px; border-radius: 4px; font-size: 13px; }
.gallery-thumbs { display: flex; gap: 8px; overflow-x: auto; padding: 12px 0; }
.gallery-thumbs button { flex: 0 0 64px; height: 80px; padding: 2px; border: 2px solid transparent; background: transparent; border-radius: 4px; cursor: pointer; }
.gallery-thumbs button.selected { border-color: var(--accent); }
.gallery-thumbs :deep(.photo) { width: 100%; height: 100%; aspect-ratio: auto; border-radius: 2px; }
.gallery-thumbs :deep(.photo-fallback span), .gallery-thumbs :deep(.photo-fallback small) { display: none; }
.lightbox { height: min(70vh, 800px); overflow: auto; position: relative; text-align: center; touch-action: pan-y pinch-zoom; }
.lightbox :deep(.photo) { width: 100%; height: 100%; aspect-ratio: auto; border-radius: 0; background: transparent; }
.lightbox :deep(.photo img) { object-fit: contain; }
.lightbox.zoomed :deep(.photo) { width: 180%; height: 180%; max-width: none; }
.zoom-control { position: sticky; top: 4px; float: right; width: 44px; height: 44px; border-radius: 50%; z-index: 1; border: 1px solid var(--line); background: var(--paper); color: var(--ink); cursor: pointer; }
.lightbox-controls { display: flex; align-items: center; justify-content: center; gap: 20px; width: 100%; }
</style>
