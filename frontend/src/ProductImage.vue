<script setup lang="ts">
import { ref, watch } from "vue";
const props = defineProps<{ src: string | null; alt: string }>();
const failed = ref(false);
watch(
  () => props.src,
  () => (failed.value = false),
);
</script>
<template>
  <div class="photo">
    <img
      v-if="src && !failed"
      :src="src"
      :alt="alt"
      loading="lazy"
      referrerpolicy="no-referrer"
      @error="failed = true"
    />
    <div v-else class="photo-fallback">
      <i class="pi pi-image"></i><span>Фото недоступно</span
      ><small>Посмотрите в магазине</small>
    </div>
    <slot />
  </div>
</template>
