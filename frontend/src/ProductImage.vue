<script setup lang="ts">
import { ref, watch, onUnmounted, computed } from "vue";
const props = defineProps<{ src: string | null; alt: string; fallbackSrc?: string | null; eager?: boolean }>();
const failed = ref(false);
const fallback = ref(false);
const retries = ref(0);
let retryTimer: ReturnType<typeof setTimeout>;
const imageSource = computed(() => fallback.value ? props.fallbackSrc :
  props.src && retries.value ? props.src + (props.src.includes('?') ? '&' : '?') + 'attempt=' + retries.value : props.src);
watch(
  () => props.src,
  () => { clearTimeout(retryTimer); failed.value = false; fallback.value = false; retries.value = 0; },
);
onUnmounted(() => clearTimeout(retryTimer));
function onError() {
  if (!fallback.value && props.src?.startsWith('/api/products/') && retries.value < 4) {
    retryTimer = setTimeout(() => { retries.value += 1; }, 500 * 2 ** retries.value);
    return;
  }
  if (!fallback.value && props.fallbackSrc && props.fallbackSrc !== props.src) fallback.value = true;
  else {
    failed.value = true;
    if (props.src?.startsWith('/api/products/')) {
      const recover = () => {
        if (document.visibilityState === 'hidden') { retryTimer = setTimeout(recover, 30000); return; }
        failed.value = false; fallback.value = false; retries.value = 0;
      };
      retryTimer = setTimeout(recover, 30000);
    }
  }
}
</script>
<template>
  <div class="photo">
    <img
      v-if="src && !failed"
      :src="imageSource || undefined"
      :alt="alt"
      :loading="eager ? 'eager' : 'lazy'"
      :fetchpriority="eager ? 'high' : 'auto'"
      decoding="async"
      referrerpolicy="no-referrer"
      @error="onError"
    />
    <div v-else class="photo-fallback">
      <i class="pi pi-image"></i><span>Не удалось загрузить фото</span
      ><small>Посмотрите в магазине</small>
    </div>
    <slot />
  </div>
</template>
